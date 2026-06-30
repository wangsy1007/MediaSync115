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
    "要求：\n"
    "1. 综合画像中的偏好类型、近期观看、收藏与喜欢的导演/演员进行推算。\n"
    "2. 不要推荐画像里已经出现过的作品。\n"
    "3. 优先推荐口碑较好、真实存在的影视剧，片名使用官方中文译名（若无则用原名）。\n"
    "4. 只返回 JSON 对象，格式为 {\"recommendations\": [{\"title\": \"\", \"year\": \"\", "
    "\"media_type\": \"movie|tv\", \"reason\": \"\"}]}。\n"
    "5. year 为首播年份字符串（可为空），reason 用一句话说明推荐理由（中文，<=40 字）。\n"
    "6. 不要输出 JSON 以外的任何内容。"
)


def _build_user_prompt(profile: dict[str, Any], count: int) -> str:
    parts: list[str] = [f"请推荐 {count} 部该用户可能喜欢的影视剧。"]

    top_genres = profile.get("top_genres") or []
    if top_genres:
        parts.append("偏好类型：" + "、".join(top_genres))

    played = profile.get("recent_played") or []
    if played:
        played_text = "、".join(
            f"{p.get('title')}{('(' + str(p.get('year')) + ')') if p.get('year') else ''}"
            for p in played
            if p.get("title")
        )
        parts.append("近期已看：" + played_text)

    resume = profile.get("in_progress") or []
    if resume:
        resume_text = "、".join(p.get("title", "") for p in resume if p.get("title"))
        parts.append("在看：" + resume_text)

    favorites = profile.get("favorites") or []
    if favorites:
        fav_text = "、".join(p.get("title", "") for p in favorites if p.get("title"))
        parts.append("收藏：" + fav_text)

    people = profile.get("top_people") or []
    if people:
        parts.append("喜欢的导演/演员：" + "、".join(people))

    year_range = profile.get("year_range")
    if year_range:
        parts.append(f"偏好年代区间：{year_range}")

    profile_summary = profile.get("summary")
    if profile_summary:
        parts.append(profile_summary)

    parts.append("请严格按系统要求的 JSON 格式返回。")
    return "\n".join(parts)


class LlmService:
    """OpenAI 兼容 Chat Completions 客户端。"""

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
