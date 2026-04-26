import logging
from html import escape

from app.core.config import settings

logger = logging.getLogger(__name__)


def resolve_poster_url(
    poster_path: str | None = None, poster_url: str | None = None
) -> str:
    raw_url = str(poster_url or "").strip()
    if raw_url:
        if raw_url.startswith("http://"):
            return raw_url.replace("http://", "https://", 1)
        if raw_url.startswith("https://"):
            return raw_url

    raw_path = str(poster_path or "").strip()
    if not raw_path:
        return ""
    if raw_path.startswith("http://"):
        return raw_path.replace("http://", "https://", 1)
    if raw_path.startswith("https://"):
        return raw_path
    if not raw_path.startswith("/"):
        raw_path = f"/{raw_path}"

    base_url = str(settings.TMDB_IMAGE_BASE_URL or "https://image.tmdb.org/t/p/w500").rstrip("/")
    return f"{base_url}{raw_path}"


def attach_poster_preview(
    text: str,
    parse_mode: str = "HTML",
    *,
    poster_path: str | None = None,
    poster_url: str | None = None,
) -> str:
    if str(parse_mode or "").upper() != "HTML":
        return text
    resolved_url = resolve_poster_url(poster_path=poster_path, poster_url=poster_url)
    if not resolved_url:
        return text
    return f'<a href="{escape(resolved_url)}">&#8205;</a>{text}'


async def tg_bot_notify(
    text: str,
    parse_mode: str = "HTML",
    *,
    poster_path: str | None = None,
    poster_url: str | None = None,
) -> None:
    try:
        from .service import tg_bot_service

        await tg_bot_service.send_notification(
            attach_poster_preview(
                text,
                parse_mode,
                poster_path=poster_path,
                poster_url=poster_url,
            ),
            parse_mode,
        )
    except Exception:
        logger.debug("TG Bot notification failed", exc_info=True)
