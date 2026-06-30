"""OpenAI 兼容的 Chat Completions 客户端，供「猜你想看」推荐推算使用。

配置（base_url / api_key / model）来自 runtime_settings_service，可覆盖
DeepSeek、通义千问、智谱、OpenAI、本地 Ollama 等绝大多数厂商。
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.services.runtime_settings_service import runtime_settings_service
from app.utils.proxy import proxy_manager

logger = logging.getLogger(__name__)

_LLM_HTTP_TIMEOUT = httpx.Timeout(60.0, connect=15.0)

_SYSTEM_PROMPT = (
    "你是一位资深影视推荐助手。根据给出的用户观影画像，推荐该用户可能喜欢、"
    "但尚未看过的影视剧。\n"
    "推荐优先级（从高到低）：\n"
    "1. 与「最近入库」影片同类型、同导演或同题材的影视。用户刚把这些加入库中，"
    "说明此刻正对这些内容有强烈兴趣，趁热推荐同类佳作效果最好。\n"
    "2. 与「最近观看」影片相似的作品。用户刚看完这些，印象最深，关联推荐最精准。\n"
    "3. 与长期偏好类型/导演匹配的口碑作品。\n"
    "4. 避开「弃剧/低完成度」作品的类型和导演。\n"
    "要求：\n"
    "5. 不要推荐画像里已经出现过的作品（尤其是最近观看和最近入库列表里的）。\n"
    "6. 片名使用官方中文译名（若无则用原名），优先推荐评分较高的作品。\n"
    "7. 只返回 JSON 对象，格式为 {\"recommendations\": [{\"title\": \"\", \"year\": \"\", "
    "\"media_type\": \"movie|tv\", \"reason\": \"\"}]}。\n"
    "8. year 为首播年份字符串（可为空），reason 用一句话说明推荐理由（中文，<=40 字），"
    "理由需提及与用户画像的关联（如\"刚入库《星际穿越》，这部同导演的太空片不容错过\"）。\n"
    "9. 不要输出 JSON 以外的任何内容。"
)


def _build_user_prompt(profile: dict[str, Any], count: int) -> str:
    parts: list[str] = [f"请推荐 {count} 部该用户可能喜欢的影视剧。"]

    # ====== 第一优先级：最近入库（最强信号） ======
    recently_added = profile.get("recently_added") or []
    if recently_added:
        parts.append(
            "【🔴 最近入库 - 最重要参考】用户刚把这些影视加进库中："
            + "、".join(recently_added)
            + "。请优先推荐与这些影片同类型、同导演、同题材的作品！"
        )

    # ====== 第二优先级：最近观看 ======
    recently_watched = profile.get("recently_watched") or []
    if recently_watched:
        parts.append(
            "【🟡 最近观看 - 重要参考】用户刚看完这些："
            + "、".join(recently_watched)
            + "。如果这些还在兴头上，趁热推荐同类影片。"
        )

    # ====== 高权重类型/导演 ======
    high_genres = profile.get("high_interest_genres") or []
    if high_genres:
        parts.append("【高关注类型】" + "、".join(high_genres))
    high_directors = profile.get("high_interest_directors") or []
    if high_directors:
        parts.append("【高关注导演】" + "、".join(high_directors))

    # ====== 长期偏好背景 ======
    top_genres = profile.get("top_genres") or []
    if top_genres:
        parts.append("【长期偏好类型】" + "、".join(top_genres))
    top_people = profile.get("top_people") or []
    if top_people:
        parts.append("【长期关注导演/演员】" + "、".join(top_people))
    older_summary = profile.get("older_watched_summary") or ""
    if older_summary:
        parts.append("【历史偏好】" + older_summary)
    year_range = profile.get("year_range")
    if year_range:
        parts.append(f"【偏好年代】{year_range}")

    # ====== 正在看 ======
    in_progress = profile.get("in_progress") or []
    if in_progress:
        resume_text = "、".join(
            f"{p.get('title')}{'(' + str(int(p['completion'])) + '%)' if p.get('completion') is not None else ''}"
            for p in in_progress if p.get("title")
        )
        parts.append("【正在看】" + resume_text)

    # ====== 避雷 ======
    low_signals = profile.get("low_interest_signals") or []
    if low_signals:
        parts.append(
            "【⚠️ 避雷】用户弃剧或不喜欢这些，请避免推荐同类型/同导演："
            + "、".join(low_signals)
        )

    profile_summary = profile.get("summary")
    if profile_summary:
        parts.append("【画像总结】" + profile_summary)

    parts.append("请严格按系统要求的 JSON 格式返回。")
    return "\n".join(parts)


class LlmService:
    """OpenAI 兼容 Chat Completions 客户端。"""

    async def check_connection(self) -> dict[str, Any]:
        """检测 LLM 配置是否可用。

        发送一条极简请求来验证 base_url / api_key / model 是否有效。
        """
        base_url = runtime_settings_service.get_llm_base_url().rstrip("/")
        api_key = runtime_settings_service.get_llm_api_key()
        model = runtime_settings_service.get_llm_model()
        if not base_url or not api_key or not model:
            return {
                "valid": False,
                "message": "LLM 未完整配置（base_url / api_key / model）",
                "model": None,
            }

        url = f"{base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": "hi"},
            ],
            "max_tokens": 4,
            "temperature": 0,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        _LLM_CHECK_TIMEOUT = httpx.Timeout(15.0, connect=10.0)
        try:
            async with proxy_manager.create_httpx_client(
                timeout=_LLM_CHECK_TIMEOUT, http2=False
            ) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json() if response.content else {}
                choices = data.get("choices") if isinstance(data, dict) else None
                if not isinstance(choices, list) or not choices:
                    return {
                        "valid": False,
                        "message": "模型返回了空响应，请检查模型名称是否正确",
                        "model": model,
                    }
                return {
                    "valid": True,
                    "message": "连接成功",
                    "model": model,
                }
        except httpx.HTTPStatusError as exc:
            detail = ""
            try:
                body = exc.response.json() if exc.response.content else {}
                if isinstance(body, dict):
                    detail = body.get("error", {}).get("message", "") or str(body)
            except Exception:
                detail = str(exc)
            return {
                "valid": False,
                "message": f"API 返回错误 (HTTP {exc.response.status_code})：{detail}",
                "model": model,
            }
        except Exception as exc:
            msg = str(exc).lower()
            if "auth" in msg or "401" in msg or "unauthorized" in msg:
                return {
                    "valid": False,
                    "message": "API Key 无效或无权访问",
                    "model": model,
                }
            return {
                "valid": False,
                "message": f"连接失败：{exc}",
                "model": model,
            }

    async def recommend(self, profile: dict[str, Any], count: int) -> list[dict[str, Any]]:
        """根据画像调用大模型返回推荐列表。

        返回 [{title, year, media_type, reason}]，解析失败返回空列表。
        """
        base_url = runtime_settings_service.get_llm_base_url().rstrip("/")
        api_key = runtime_settings_service.get_llm_api_key()
        model = runtime_settings_service.get_llm_model()
        if not base_url or not api_key or not model:
            raise ValueError("LLM 未完整配置（base_url / api_key / model）")

        url = f"{base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_prompt(profile, count)},
            ],
            "temperature": 0.7,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with proxy_manager.create_httpx_client(
            timeout=_LLM_HTTP_TIMEOUT, http2=False
        ) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json() if response.content else {}

        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list) or not choices:
            return []
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = str(message.get("content") or "").strip() if isinstance(message, dict) else ""
        if not content:
            return []

        return self._parse_recommendations(content)

    @staticmethod
    def _parse_recommendations(content: str) -> list[dict[str, Any]]:
        """从模型返回内容中解析推荐列表，容错处理。"""
        try:
            parsed = json.loads(content)
        except Exception:
            # 兜底：截取首个 JSON 对象片段
            start = content.find("{")
            end = content.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return []
            try:
                parsed = json.loads(content[start : end + 1])
            except Exception:
                return []
        if not isinstance(parsed, dict):
            return []
        raw_items = parsed.get("recommendations")
        if not isinstance(raw_items, list):
            # 兼容部分模型直接返回列表
            raw_items = parsed.get("data") if isinstance(parsed.get("data"), list) else None
        if not isinstance(raw_items, list):
            return []

        results: list[dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            media_type = str(item.get("media_type") or "").strip().lower()
            if media_type not in {"movie", "tv"}:
                media_type = "movie"
            year = str(item.get("year") or "").strip()
            if year and not year[:4].isdigit():
                year = ""
            results.append(
                {
                    "title": title,
                    "year": year,
                    "media_type": media_type,
                    "reason": str(item.get("reason") or "").strip(),
                }
            )
        return results


llm_service = LlmService()
