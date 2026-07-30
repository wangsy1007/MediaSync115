"""Emby 媒体库封面生成。

参考 jellyfin-library-poster / MoviePilot MediaCoverGenerator：
从媒体库取最新海报拼图，生成封面并可选上传到 Emby。
"""

from __future__ import annotations

import asyncio
import colorsys
import io
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from app.core.timezone_utils import beijing_now
from app.services.emby_service import emby_service
from app.services.operation_log_service import operation_log_service
from app.services.runtime_settings_service import runtime_settings_service

logger = logging.getLogger(__name__)

LIBRARY_COVER_STYLES = ("grid", "blur", "single")
LIBRARY_COVER_SORTS = (
    "DateCreated",
    "DateLastContentAdded",
    "PremiereDate",
    "Random",
    "SortName",
)

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
)


class LibraryCoverService:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._running = False
        self._last_started_at: datetime | None = None
        self._last_finished_at: datetime | None = None
        self._last_trigger: str = ""
        self._last_error: str = ""
        self._last_summary: dict[str, Any] | None = None

    def get_runtime_status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "last_started_at": self._last_started_at.isoformat()
            if isinstance(self._last_started_at, datetime)
            else "",
            "last_finished_at": self._last_finished_at.isoformat()
            if isinstance(self._last_finished_at, datetime)
            else "",
            "last_trigger": self._last_trigger,
            "last_error": self._last_error,
            "last_summary": self._last_summary,
        }

    def get_output_dir(self) -> Path:
        root = Path("data") / "library_covers"
        root.mkdir(parents=True, exist_ok=True)
        return root

    async def start_generate(self, *, trigger: str = "manual") -> dict[str, Any]:
        if self._running:
            return {"started": False, "message": "媒体库封面生成正在进行中"}
        if not runtime_settings_service.get_emby_url() or not runtime_settings_service.get_emby_api_key():
            return {"started": False, "message": "请先配置 Emby URL 与 API Key"}

        asyncio.create_task(self._run_safe(trigger=trigger))
        return {"started": True, "message": "已开始生成媒体库封面"}

    async def _run_safe(self, *, trigger: str) -> None:
        async with self._lock:
            if self._running:
                return
            self._running = True
            self._last_started_at = beijing_now()
            self._last_trigger = trigger
            self._last_error = ""
            try:
                summary = await self.generate_all(trigger=trigger)
                self._last_summary = summary
            except Exception as exc:
                self._last_error = str(exc) or "未知错误"
                logger.exception("媒体库封面生成失败: %s", exc)
                await operation_log_service.log_background_event(
                    source_type="background_task",
                    module="library_cover",
                    action="library_cover.failed",
                    status="failed",
                    message=f"媒体库封面生成失败：{self._last_error}",
                    extra={"trigger": trigger},
                )
            finally:
                self._running = False
                self._last_finished_at = beijing_now()

    async def generate_all(self, *, trigger: str = "manual") -> dict[str, Any]:
        style = runtime_settings_service.get_library_cover_style()
        sort_by = runtime_settings_service.get_library_cover_sort_by()
        poster_count = runtime_settings_service.get_library_cover_poster_count()
        show_title = runtime_settings_service.get_library_cover_show_title()
        upload = runtime_settings_service.get_library_cover_upload()
        exclude = {
            name.casefold()
            for name in runtime_settings_service.get_library_cover_exclude()
        }
        title_map = runtime_settings_service.get_library_cover_title_map()
        width = runtime_settings_service.get_library_cover_width()
        height = runtime_settings_service.get_library_cover_height()

        libraries = await emby_service.list_media_libraries()
        summary: dict[str, Any] = {
            "trigger": trigger,
            "style": style,
            "sort_by": sort_by,
            "upload": upload,
            "total": 0,
            "success": 0,
            "skipped": 0,
            "failed": 0,
            "items": [],
        }

        await operation_log_service.log_background_event(
            source_type="background_task",
            module="library_cover",
            action="library_cover.start",
            status="info",
            message=f"开始生成媒体库封面（风格={style}，排序={sort_by}）",
            extra={"trigger": trigger, "libraries": len(libraries)},
        )

        for library in libraries:
            name = str(library.get("name") or "").strip()
            item_id = str(library.get("id") or "").strip()
            if not name or not item_id:
                continue
            if name.casefold() in exclude:
                summary["skipped"] += 1
                summary["items"].append(
                    {"name": name, "status": "skipped", "message": "已排除"}
                )
                continue

            summary["total"] += 1
            display_title = str(title_map.get(name) or name).strip() or name
            try:
                result = await self._generate_one(
                    library_id=item_id,
                    library_name=name,
                    display_title=display_title,
                    style=style,
                    sort_by=sort_by,
                    poster_count=poster_count,
                    show_title=show_title,
                    upload=upload,
                    width=width,
                    height=height,
                )
                summary["items"].append(result)
                if result.get("status") == "success":
                    summary["success"] += 1
                elif result.get("status") == "skipped":
                    summary["skipped"] += 1
                else:
                    summary["failed"] += 1
            except Exception as exc:
                summary["failed"] += 1
                summary["items"].append(
                    {
                        "name": name,
                        "status": "failed",
                        "message": str(exc) or "生成失败",
                    }
                )
                logger.warning("媒体库封面生成失败 name=%s: %s", name, exc)

        await operation_log_service.log_background_event(
            source_type="background_task",
            module="library_cover",
            action="library_cover.finish",
            status="success" if summary["failed"] == 0 else "warning",
            message=(
                f"媒体库封面生成完成：成功 {summary['success']}，"
                f"跳过 {summary['skipped']}，失败 {summary['failed']}"
            ),
            extra=summary,
        )
        return summary

    async def _generate_one(
        self,
        *,
        library_id: str,
        library_name: str,
        display_title: str,
        style: str,
        sort_by: str,
        poster_count: int,
        show_title: bool,
        upload: bool,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        items = await emby_service.list_library_poster_items(
            library_id,
            sort_by=sort_by,
            limit=max(poster_count * 3, 30),
        )
        if not items:
            return {
                "name": library_name,
                "status": "skipped",
                "message": "媒体库无可用海报",
            }

        selected = items[: max(1, poster_count)]
        images: list[Image.Image] = []
        for item in selected:
            item_id = str(item.get("Id") or "").strip()
            raw = await emby_service.download_item_primary_image(item_id)
            if not raw:
                continue
            try:
                img = Image.open(io.BytesIO(raw)).convert("RGB")
                images.append(img)
            except Exception:
                continue

        if not images:
            return {
                "name": library_name,
                "status": "skipped",
                "message": "海报下载失败",
            }

        # 不足数量时循环补齐（与 jellyfin-library-poster 一致）
        while len(images) < poster_count:
            images.append(images[len(images) % len(images)].copy())

        cover = await asyncio.to_thread(
            self._compose_cover,
            images[:poster_count],
            style=style,
            title=display_title if show_title else "",
            width=width,
            height=height,
        )

        output_dir = self.get_output_dir()
        safe_name = "".join(
            ch if ch.isalnum() or ch in ("-", "_", " ", ".") else "_"
            for ch in library_name
        ).strip() or library_id
        output_path = output_dir / f"{safe_name}.jpg"
        await asyncio.to_thread(cover.save, output_path, "JPEG", quality=92, optimize=True)

        uploaded = False
        if upload:
            buf = io.BytesIO()
            cover.save(buf, format="JPEG", quality=92, optimize=True)
            uploaded = await emby_service.upload_item_primary_image(
                library_id, buf.getvalue(), content_type="image/jpeg"
            )
            if not uploaded:
                return {
                    "name": library_name,
                    "status": "failed",
                    "message": "封面已生成但上传 Emby 失败",
                    "path": str(output_path),
                }

        return {
            "name": library_name,
            "status": "success",
            "message": "已上传" if uploaded else "已生成本地预览",
            "path": str(output_path),
            "uploaded": uploaded,
        }

    def _compose_cover(
        self,
        posters: list[Image.Image],
        *,
        style: str,
        title: str,
        width: int,
        height: int,
    ) -> Image.Image:
        style_key = (style or "grid").strip().lower()
        if style_key == "blur":
            return self._style_blur(posters, title=title, width=width, height=height)
        if style_key == "single":
            return self._style_single(posters, title=title, width=width, height=height)
        return self._style_grid(posters, title=title, width=width, height=height)

    def _style_grid(
        self,
        posters: list[Image.Image],
        *,
        title: str,
        width: int,
        height: int,
    ) -> Image.Image:
        canvas = Image.new("RGB", (width, height), (18, 18, 22))
        cols = 3
        rows = 3
        gap = max(8, width // 120)
        cell_w = (width - gap * (cols + 1)) // cols
        cell_h = (height - gap * (rows + 1)) // rows
        for idx in range(cols * rows):
            poster = posters[idx % len(posters)]
            tile = self._cover_fit(poster, cell_w, cell_h)
            x = gap + (idx % cols) * (cell_w + gap)
            y = gap + (idx // cols) * (cell_h + gap)
            canvas.paste(tile, (x, y))
        if title:
            self._draw_title_banner(canvas, title)
        return canvas

    def _style_blur(
        self,
        posters: list[Image.Image],
        *,
        title: str,
        width: int,
        height: int,
    ) -> Image.Image:
        base = self._cover_fit(posters[0], width, height)
        blurred = base.filter(ImageFilter.GaussianBlur(radius=28))
        blurred = ImageEnhance.Brightness(blurred).enhance(0.55)
        canvas = blurred.convert("RGBA")

        # 左侧主题色渐变遮罩
        theme = self._pick_theme_color(posters[0])
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for x in range(width):
            alpha = int(210 * (1 - x / max(width - 1, 1)) ** 1.2)
            color = (*theme, max(40, min(220, alpha)))
            draw.line([(x, 0), (x, height)], fill=color)
        canvas = Image.alpha_composite(canvas, overlay)

        # 右侧倾斜海报堆叠
        stack_count = min(5, len(posters))
        poster_h = int(height * 0.72)
        poster_w = int(poster_h * 2 / 3)
        start_x = int(width * 0.42)
        start_y = int((height - poster_h) / 2)
        for i in range(stack_count):
            poster = self._cover_fit(posters[i], poster_w, poster_h).convert("RGBA")
            shadowed = self._add_shadow(poster)
            angle = -8 + i * 4
            rotated = shadowed.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
            ox = start_x + i * int(poster_w * 0.28)
            oy = start_y + (i % 2) * 12
            canvas.alpha_composite(rotated, (ox, oy))

        result = canvas.convert("RGB")
        if title:
            self._draw_title_text(result, title, position="left")
        return result

    def _style_single(
        self,
        posters: list[Image.Image],
        *,
        title: str,
        width: int,
        height: int,
    ) -> Image.Image:
        canvas = self._cover_fit(posters[0], width, height)
        # 底部渐变
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        for y in range(height):
            t = y / max(height - 1, 1)
            alpha = int(max(0, (t - 0.45) / 0.55) * 190)
            draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
        if title:
            self._draw_title_text(canvas, title, position="bottom")
        return canvas

    @staticmethod
    def _cover_fit(image: Image.Image, width: int, height: int) -> Image.Image:
        src = image.convert("RGB")
        src_ratio = src.width / max(src.height, 1)
        dst_ratio = width / max(height, 1)
        if src_ratio > dst_ratio:
            new_h = height
            new_w = int(height * src_ratio)
        else:
            new_w = width
            new_h = int(width / max(src_ratio, 0.01))
        resized = src.resize((max(1, new_w), max(1, new_h)), Image.Resampling.LANCZOS)
        left = max(0, (resized.width - width) // 2)
        top = max(0, (resized.height - height) // 2)
        return resized.crop((left, top, left + width, top + height))

    @staticmethod
    def _add_shadow(img: Image.Image) -> Image.Image:
        offset = (8, 8)
        blur_radius = 10
        shadow_color = (0, 0, 0, 110)
        shadow_w = img.width + offset[0] + blur_radius * 2
        shadow_h = img.height + offset[1] + blur_radius * 2
        shadow = Image.new("RGBA", (shadow_w, shadow_h), (0, 0, 0, 0))
        shadow_layer = Image.new("RGBA", img.size, shadow_color)
        shadow.paste(shadow_layer, (blur_radius + offset[0], blur_radius + offset[1]))
        shadow = shadow.filter(ImageFilter.GaussianBlur(blur_radius))
        result = Image.new("RGBA", shadow.size, (0, 0, 0, 0))
        result.paste(img, (blur_radius, blur_radius), img)
        return Image.alpha_composite(shadow, result)

    @staticmethod
    def _pick_theme_color(image: Image.Image) -> tuple[int, int, int]:
        small = image.convert("RGB").resize((48, 48), Image.Resampling.BILINEAR)
        colors = small.getcolors(48 * 48) or []
        scored: list[tuple[float, tuple[int, int, int]]] = []
        for count, rgb in colors:
            r, g, b = rgb
            h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
            if l < 0.18 or l > 0.82 or s < 0.18:
                continue
            scored.append((count * (0.4 + s), (r, g, b)))
        if scored:
            scored.sort(key=lambda item: item[0], reverse=True)
            return scored[0][1]
        h = random.random()
        r, g, b = colorsys.hls_to_rgb(h, 0.35, 0.55)
        return (int(r * 255), int(g * 255), int(b * 255))

    def _load_font(self, size: int) -> ImageFont.ImageFont:
        for path in _FONT_CANDIDATES:
            try:
                if Path(path).exists():
                    return ImageFont.truetype(path, size=size)
            except Exception:
                continue
        return ImageFont.load_default()

    def _draw_title_banner(self, canvas: Image.Image, title: str) -> None:
        width, height = canvas.size
        banner_h = max(72, height // 8)
        overlay = Image.new("RGBA", (width, banner_h), (0, 0, 0, 150))
        base = canvas.convert("RGBA")
        base.paste(overlay, (0, height - banner_h), overlay)
        canvas.paste(base.convert("RGB"))
        self._draw_title_text(canvas, title, position="bottom")

    def _draw_title_text(
        self,
        canvas: Image.Image,
        title: str,
        *,
        position: str = "bottom",
    ) -> None:
        text = str(title or "").strip()
        if not text:
            return
        width, height = canvas.size
        font_size = max(36, min(width, height) // 12)
        font = self._load_font(font_size)
        draw = ImageDraw.Draw(canvas)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        if position == "left":
            x = max(36, width // 18)
            y = (height - text_h) // 2
        else:
            x = (width - text_w) // 2
            y = height - text_h - max(28, height // 18)
        # 阴影
        draw.text((x + 3, y + 3), text, font=font, fill=(0, 0, 0))
        draw.text((x, y), text, font=font, fill=(255, 255, 255))


library_cover_service = LibraryCoverService()
