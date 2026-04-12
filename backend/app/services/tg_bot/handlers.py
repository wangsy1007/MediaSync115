import logging
from html import escape
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logger = logging.getLogger(__name__)

ITEMS_PER_PAGE = 5
RESOURCE_PAGE_SIZE = 8


def _auth_check(allowed_users: list) -> callable:
    def decorator(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if allowed_users:
                user_id = update.effective_user.id
                if user_id not in allowed_users:
                    await update.effective_message.reply_text(
                        "你没有权限使用此机器人。"
                    )
                    return
            return await func(update, context)

        return wrapper

    return decorator


def register_handlers(app: Application, allowed_users: list) -> None:
    auth = _auth_check(allowed_users)

    app.add_handler(CommandHandler("start", auth(cmd_start)))
    app.add_handler(CommandHandler("help", auth(cmd_help)))
    app.add_handler(CommandHandler(["s", "search"], auth(cmd_search)))
    app.add_handler(CommandHandler("subs", auth(cmd_subs)))
    app.add_handler(CommandHandler("run", auth(cmd_run)))
    app.add_handler(CommandHandler("status", auth(cmd_status)))
    app.add_handler(CommandHandler("offline", auth(cmd_offline)))
    app.add_handler(CommandHandler("recent", auth(cmd_recent)))
    app.add_handler(CommandHandler("id", auth(cmd_id)))

    app.add_handler(CallbackQueryHandler(auth(cb_handler)))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, auth(msg_text)))


# ── Commands ──────────────────────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "<b>MediaSync115 Bot</b>\n\n"
        "搜索影视、转存资源、管理订阅，一切尽在掌控。\n\n"
        "<b>常用命令：</b>\n"
        "/s &lt;关键词&gt; - 搜索影视\n"
        "/subs - 查看订阅列表\n"
        "/run - 触发订阅检查\n"
        "/status - 系统状态\n"
        "/offline - 离线任务列表\n"
        "/recent - 最近下载记录\n"
        "/id - 获取当前聊天 ID\n"
        "/help - 帮助信息\n\n"
        "也可以直接发送影视名称进行搜索。"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "<b>命令列表</b>\n\n"
        "/s &lt;关键词&gt; - 搜索影视（TMDB）\n"
        "/subs - 查看所有订阅\n"
        "/run - 手动执行订阅检查\n"
        "/run &lt;频道&gt; - 执行指定频道（pansou/hdhive/tg）\n"
        "/status - 查看系统状态\n"
        "/offline - 查看离线下载任务\n"
        "/recent - 最近下载记录\n"
        "/id - 获取当前聊天 ID（用于配置通知）\n\n"
        "<b>交互操作：</b>\n"
        "搜索结果中可点击按钮查看详情、搜索资源、转存到115网盘或添加订阅。"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    await update.message.reply_text(
        f"Chat ID: <code>{chat_id}</code>\nUser ID: <code>{user_id}</code>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyword = " ".join(context.args) if context.args else ""
    if not keyword:
        await update.message.reply_text("请输入搜索关键词，例如：/s 流浪地球")
        return
    await _do_search(update, context, keyword, page=1)


async def msg_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyword = (update.message.text or "").strip()
    if not keyword:
        return
    await _do_search(update, context, keyword, page=1)


async def cmd_subs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _show_subscriptions(update, context, page=1)


async def cmd_run(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channel = context.args[0] if context.args else "all"
    valid_channels = {"all", "pansou", "hdhive", "tg"}
    if channel not in valid_channels:
        await update.message.reply_text(
            f"无效的频道，可选：{', '.join(sorted(valid_channels))}"
        )
        return

    msg = await update.message.reply_text("正在启动订阅检查...")

    try:
        from app.services.subscription_run_task_service import (
            subscription_run_task_service,
        )

        result = await subscription_run_task_service.start(channel)

        if result.get("already_running"):
            await msg.edit_text("订阅检查任务正在执行中，请稍后再试。")
            return

        task_id = result.get("task_id", "")
        await msg.edit_text(
            f"订阅检查已启动\n"
            f"频道: <b>{escape(channel)}</b>\n"
            f"任务ID: <code>{escape(task_id)}</code>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.exception("Failed to start subscription run")
        await msg.edit_text(f"启动失败: {escape(str(e))}")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["<b>系统状态</b>\n"]

    try:
        from app.services.pan115_service import pan115_service

        cookie_result = await pan115_service.check_cookie_valid()
        if cookie_result.get("valid"):
            user_info = cookie_result.get("user_info") or {}
            username = user_info.get("user_name", "未知")
            lines.append(f"115网盘: 已连接 ({escape(username)})")
        else:
            lines.append("115网盘: 未连接")
    except Exception:
        lines.append("115网盘: 检测失败")

    try:
        from app.services.pan115_service import pan115_service

        quota = await pan115_service.get_offline_quota_info()
        total = quota.get("total_quota")
        used = quota.get("used_quota")
        remaining = quota.get("remaining_quota")
        if total is not None:
            lines.append(f"离线配额: {used}/{total}（剩余 {remaining}）")
    except Exception:
        pass

    try:
        from app.core.database import async_session_maker
        from sqlalchemy import select, func
        from app.models.models import Subscription

        async with async_session_maker() as db:
            count_result = await db.execute(
                select(func.count())
                .select_from(Subscription)
                .where(Subscription.is_active == True)
            )
            active_count = count_result.scalar() or 0
        lines.append(f"活跃订阅: {active_count} 部")
    except Exception:
        pass

    from .service import tg_bot_service

    bot_status = tg_bot_service.status()
    lines.append(f"TG Bot: {'运行中' if bot_status['running'] else '已停止'}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def cmd_offline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        from app.services.pan115_service import pan115_service

        result = await pan115_service.offline_task_list(page=1)
        tasks = result.get("tasks") or []

        if not tasks:
            await update.message.reply_text("当前没有离线下载任务。")
            return

        lines = ["<b>离线下载任务</b>\n"]
        for i, task in enumerate(tasks[:15], 1):
            name = escape(str(task.get("name", "未知"))[:50])
            percent = task.get("percentDone") or task.get("percent") or 0
            status_icon = "done" if percent >= 100 else f"{percent:.0f}%"
            lines.append(f"{i}. {name} [{status_icon}]")

        if len(tasks) > 15:
            lines.append(f"\n... 共 {len(tasks)} 个任务")

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception("Failed to get offline tasks")
        await update.message.reply_text(f"获取离线任务失败: {escape(str(e))}")


async def cmd_recent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        from app.core.database import async_session_maker
        from sqlalchemy import select
        from app.models.models import DownloadRecord, Subscription

        async with async_session_maker() as db:
            result = await db.execute(
                select(DownloadRecord, Subscription.title)
                .join(Subscription, DownloadRecord.subscription_id == Subscription.id)
                .order_by(DownloadRecord.created_at.desc())
                .limit(10)
            )
            rows = result.all()

        if not rows:
            await update.message.reply_text("暂无下载记录。")
            return

        lines = ["<b>最近下载记录</b>\n"]
        for record, title in rows:
            status_map = {
                "completed": "done",
                "failed": "fail",
                "pending": "wait",
                "downloading": "...",
            }
            status = (
                status_map.get(record.status.value, record.status.value)
                if record.status
                else "?"
            )
            name = escape(str(record.resource_name or title)[:45])
            lines.append(f"[{status}] {name}")

        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.exception("Failed to get recent downloads")
        await update.message.reply_text(f"获取下载记录失败: {escape(str(e))}")


# ── Callback Query Router ────────────────────────────────


async def cb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    await query.answer()

    try:
        if data == "noop":
            return
        elif data.startswith("sp:"):
            page = int(data.split(":")[1])
            keyword = context.user_data.get("last_search_keyword", "")
            if keyword:
                await _do_search(update, context, keyword, page, edit=True)
        elif data.startswith("det:"):
            parts = data.split(":")
            tmdb_id, media_type = int(parts[1]), parts[2]
            await _show_detail(update, context, tmdb_id, media_type)
        elif data.startswith("res:"):
            parts = data.split(":")
            tmdb_id, media_type = int(parts[1]), parts[2]
            await _show_resource_menu(update, context, tmdb_id, media_type)
        elif data.startswith("r115:"):
            parts = data.split(":")
            tmdb_id, media_type = int(parts[1]), parts[2]
            await _search_115_resources(update, context, tmdb_id, media_type)
        elif data.startswith("rmag:"):
            parts = data.split(":")
            tmdb_id, media_type = int(parts[1]), parts[2]
            await _search_magnet_resources(update, context, tmdb_id, media_type)
        elif data.startswith("sv:"):
            idx = int(data.split(":")[1])
            await _save_115_resource(update, context, idx)
        elif data.startswith("ol:"):
            idx = int(data.split(":")[1])
            await _add_offline_task(update, context, idx)
        elif data.startswith("sub:"):
            parts = data.split(":")
            tmdb_id, media_type = int(parts[1]), parts[2]
            await _add_subscription(update, context, tmdb_id, media_type)
        elif data.startswith("unsub:"):
            sub_id = int(data.split(":")[1])
            await _delete_subscription(update, context, sub_id)
        elif data.startswith("subp:"):
            page = int(data.split(":")[1])
            await _show_subscriptions(update, context, page, edit=True)
        elif data.startswith("back:"):
            target = data.split(":")[1]
            if target == "search":
                keyword = context.user_data.get("last_search_keyword", "")
                page = context.user_data.get("last_search_page", 1)
                if keyword:
                    await _do_search(update, context, keyword, page, edit=True)
        elif data.startswith("r115p:"):
            # 115 resource pagination: r115p:<page>
            page = int(data.split(":")[1])
            await _show_115_resource_page(update, context, page)
        elif data.startswith("rmagp:"):
            page = int(data.split(":")[1])
            await _show_magnet_resource_page(update, context, page)
    except Exception:
        logger.exception("Callback handler error for data=%s", data)
        try:
            await query.edit_message_text("操作出错，请重试。")
        except Exception:
            pass


# ── Search ────────────────────────────────────────────────


async def _do_search(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    keyword: str,
    page: int = 1,
    edit: bool = False,
):
    context.user_data["last_search_keyword"] = keyword
    context.user_data["last_search_page"] = page

    target = update.callback_query.message if edit else update.message
    placeholder = None
    if not edit:
        placeholder = await target.reply_text(f"正在搜索: {escape(keyword)} ...")

    try:
        from app.services.tmdb_service import tmdb_service

        result = await tmdb_service.search_multi(keyword, page=page)
    except Exception as e:
        text = f"搜索失败: {escape(str(e))}"
        if placeholder:
            await placeholder.edit_text(text)
        elif edit:
            await update.callback_query.edit_message_text(text)
        return

    items = result.get("results") or result.get("items") or []
    total_pages = result.get("total_pages", 1)
    total_results = result.get("total_results", 0)

    if not items:
        text = f'未找到 "{escape(keyword)}" 的相关结果。'
        if placeholder:
            await placeholder.edit_text(text)
        elif edit:
            await update.callback_query.edit_message_text(text)
        return

    # Store search results for detail view
    search_items = []
    for item in items[:ITEMS_PER_PAGE]:
        media_type = item.get("media_type", "movie")
        if media_type not in ("movie", "tv"):
            continue
        tmdb_id = item.get("id")
        title = item.get("title") or item.get("name") or "未知"
        year = ""
        date_str = item.get("release_date") or item.get("first_air_date") or ""
        if date_str:
            year = date_str[:4]
        rating = item.get("vote_average", 0)
        search_items.append(
            {
                "tmdb_id": tmdb_id,
                "media_type": media_type,
                "title": title,
                "year": year,
                "rating": rating,
                "poster_path": item.get("poster_path"),
                "overview": item.get("overview", ""),
            }
        )

    context.user_data["search_results"] = search_items

    lines = [f"<b>搜索: {escape(keyword)}</b>  ({total_results} 个结果)\n"]
    buttons = []
    for i, item in enumerate(search_items):
        type_label = "movie" if item["media_type"] == "movie" else "tv"
        year_str = f" ({item['year']})" if item["year"] else ""
        rating_str = f" {item['rating']:.1f}" if item["rating"] else ""
        lines.append(
            f"{i + 1}. [{type_label}] {escape(item['title'])}{year_str}{rating_str}"
        )
        buttons.append(
            [
                InlineKeyboardButton(
                    f"{i + 1}. {item['title'][:30]}{year_str}",
                    callback_data=f"det:{item['tmdb_id']}:{item['media_type']}",
                )
            ]
        )

    # Pagination
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("< 上一页", callback_data=f"sp:{page - 1}"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("下一页 >", callback_data=f"sp:{page + 1}"))
    if nav:
        buttons.append(nav)

    markup = InlineKeyboardMarkup(buttons)
    text = "\n".join(lines)

    if placeholder:
        await placeholder.edit_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup
        )
    elif edit:
        await update.callback_query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup
        )


# ── Detail ────────────────────────────────────────────────


async def _show_detail(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    tmdb_id: int,
    media_type: str,
):
    query = update.callback_query

    # Find item from cached search results
    cached = context.user_data.get("search_results") or []
    item = next(
        (
            r
            for r in cached
            if r["tmdb_id"] == tmdb_id and r["media_type"] == media_type
        ),
        None,
    )

    try:
        from app.services.tmdb_service import tmdb_service

        if media_type == "movie":
            detail = await tmdb_service.get_movie_detail(tmdb_id)
        else:
            detail = await tmdb_service.get_tv_detail(tmdb_id)
    except Exception:
        detail = None

    if detail:
        title = detail.get("title") or detail.get("name") or "未知"
        overview = detail.get("overview") or "暂无简介"
        rating = detail.get("vote_average", 0)
        date_str = detail.get("release_date") or detail.get("first_air_date") or ""
        year = date_str[:4] if date_str else ""
        genres = ", ".join(g.get("name", "") for g in (detail.get("genres") or [])[:5])
        runtime = (
            detail.get("runtime") or detail.get("episode_run_time", [None])[0]
            if detail.get("episode_run_time")
            else None
        )
        seasons = detail.get("number_of_seasons")
        episodes = detail.get("number_of_episodes")
    elif item:
        title = item["title"]
        overview = item.get("overview", "暂无简介")
        rating = item.get("rating", 0)
        year = item.get("year", "")
        genres = ""
        runtime = None
        seasons = None
        episodes = None
    else:
        await query.edit_message_text("未找到详情信息。")
        return

    # Store detail for later use
    context.user_data["current_detail"] = {
        "tmdb_id": tmdb_id,
        "media_type": media_type,
        "title": title,
        "year": year,
        "rating": rating,
        "poster_path": (detail or item or {}).get("poster_path"),
        "overview": overview,
    }

    type_label = "电影" if media_type == "movie" else "电视剧"
    lines = [
        f"<b>{escape(title)}</b>",
        f"类型: {type_label}",
    ]
    if year:
        lines.append(f"年份: {year}")
    if rating:
        lines.append(f"评分: {rating:.1f}")
    if genres:
        lines.append(f"类型: {genres}")
    if runtime:
        lines.append(f"时长: {runtime} 分钟")
    if seasons:
        lines.append(f"季数: {seasons}  集数: {episodes or '?'}")
    lines.append(f"\n{escape(overview[:300])}")

    buttons = [
        [
            InlineKeyboardButton(
                "搜索资源", callback_data=f"res:{tmdb_id}:{media_type}"
            ),
            InlineKeyboardButton(
                "添加订阅", callback_data=f"sub:{tmdb_id}:{media_type}"
            ),
        ],
        [InlineKeyboardButton("< 返回搜索", callback_data="back:search")],
    ]

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ── Resource Menu ─────────────────────────────────────────


async def _show_resource_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    tmdb_id: int,
    media_type: str,
):
    query = update.callback_query
    detail = context.user_data.get("current_detail") or {}
    title = detail.get("title", "未知")

    buttons = [
        [
            InlineKeyboardButton(
                "115 网盘资源", callback_data=f"r115:{tmdb_id}:{media_type}"
            ),
        ],
        [
            InlineKeyboardButton(
                "磁力链接", callback_data=f"rmag:{tmdb_id}:{media_type}"
            ),
        ],
        [
            InlineKeyboardButton(
                "添加订阅", callback_data=f"sub:{tmdb_id}:{media_type}"
            ),
        ],
        [
            InlineKeyboardButton(
                "< 返回详情", callback_data=f"det:{tmdb_id}:{media_type}"
            )
        ],
    ]

    await query.edit_message_text(
        f"<b>{escape(title)}</b> - 选择资源类型",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ── 115 Resources ─────────────────────────────────────────


async def _search_115_resources(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    tmdb_id: int,
    media_type: str,
):
    query = update.callback_query
    detail = context.user_data.get("current_detail") or {}
    title = detail.get("title", "未知")

    await query.edit_message_text(f"正在搜索 115 资源: {escape(title)} ...")

    resources = []

    # Search via pansou
    try:
        from app.services.tmdb_service import tmdb_service

        if media_type == "movie":
            tmdb_detail = await tmdb_service.get_movie_detail(tmdb_id)
        else:
            tmdb_detail = await tmdb_service.get_tv_detail(tmdb_id)

        keywords = _build_search_keywords(tmdb_detail, media_type)
        from app.services.pansou_service import pansou_service

        for kw in keywords[:3]:
            try:
                pansou_result = await pansou_service.search(kw, resource_type="115")
                items = (
                    pansou_result
                    if isinstance(pansou_result, list)
                    else (pansou_result.get("list") or [])
                )
                for item in items[:10]:
                    share_link = (
                        item.get("share_link")
                        or item.get("url")
                        or item.get("link")
                        or ""
                    )
                    if share_link and not any(
                        r["share_link"] == share_link for r in resources
                    ):
                        resources.append(
                            {
                                "title": item.get("title") or item.get("name") or kw,
                                "share_link": share_link,
                                "size": item.get("size") or "",
                                "quality": item.get("quality")
                                or item.get("resolution")
                                or "",
                                "source": "pansou",
                            }
                        )
                if resources:
                    break
            except Exception:
                continue
    except Exception:
        logger.debug("Pansou 115 search failed for tmdb_id=%s", tmdb_id)

    context.user_data["cached_115_resources"] = resources
    context.user_data["cached_115_tmdb_id"] = tmdb_id
    context.user_data["cached_115_media_type"] = media_type

    await _show_115_resource_page(update, context, page=1)


async def _show_115_resource_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    page: int,
):
    resources = context.user_data.get("cached_115_resources") or []
    tmdb_id = context.user_data.get("cached_115_tmdb_id", 0)
    media_type = context.user_data.get("cached_115_media_type", "movie")
    detail = context.user_data.get("current_detail") or {}
    title = detail.get("title", "未知")

    query = update.callback_query

    if not resources:
        buttons = [
            [
                InlineKeyboardButton(
                    "< 返回", callback_data=f"res:{tmdb_id}:{media_type}"
                )
            ]
        ]
        await query.edit_message_text(
            f"<b>{escape(title)}</b> - 未找到 115 资源",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    total_pages = (len(resources) + RESOURCE_PAGE_SIZE - 1) // RESOURCE_PAGE_SIZE
    page = max(1, min(page, total_pages))
    start = (page - 1) * RESOURCE_PAGE_SIZE
    page_items = resources[start : start + RESOURCE_PAGE_SIZE]

    lines = [f"<b>{escape(title)}</b> - 115 资源 ({len(resources)}个)\n"]
    buttons = []
    for i, res in enumerate(page_items):
        global_idx = start + i
        res_title = escape(str(res["title"])[:40])
        size = f" [{res['size']}]" if res.get("size") else ""
        quality = f" {res['quality']}" if res.get("quality") else ""
        lines.append(f"{global_idx + 1}. {res_title}{quality}{size}")
        buttons.append(
            [
                InlineKeyboardButton(
                    f"转存 {global_idx + 1}: {str(res['title'])[:25]}",
                    callback_data=f"sv:{global_idx}",
                )
            ]
        )

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("< 上页", callback_data=f"r115p:{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("下页 >", callback_data=f"r115p:{page + 1}"))
    buttons.append(nav)
    buttons.append(
        [InlineKeyboardButton("< 返回", callback_data=f"res:{tmdb_id}:{media_type}")]
    )

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ── Magnet Resources ──────────────────────────────────────


async def _search_magnet_resources(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    tmdb_id: int,
    media_type: str,
):
    query = update.callback_query
    detail = context.user_data.get("current_detail") or {}
    title = detail.get("title", "未知")

    await query.edit_message_text(f"正在搜索磁力资源: {escape(title)} ...")

    resources = []

    # Search via butailing
    try:
        from app.services.butailing_service import butailing_service

        bt_results = await butailing_service.search_magnets(title, media_type)
        for item in bt_results:
            magnet = item.get("magnet", "")
            if magnet and not any(r["magnet"] == magnet for r in resources):
                resources.append(
                    {
                        "name": item.get("name") or "未知",
                        "magnet": magnet,
                        "size": item.get("size") or "",
                        "quality": item.get("quality") or "",
                        "source": "butailing",
                    }
                )
    except Exception:
        logger.debug("Butailing magnet search failed for title=%s", title)

    context.user_data["cached_magnet_resources"] = resources
    context.user_data["cached_magnet_tmdb_id"] = tmdb_id
    context.user_data["cached_magnet_media_type"] = media_type

    await _show_magnet_resource_page(update, context, page=1)


async def _show_magnet_resource_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    page: int,
):
    resources = context.user_data.get("cached_magnet_resources") or []
    tmdb_id = context.user_data.get("cached_magnet_tmdb_id", 0)
    media_type = context.user_data.get("cached_magnet_media_type", "movie")
    detail = context.user_data.get("current_detail") or {}
    title = detail.get("title", "未知")

    query = update.callback_query

    if not resources:
        buttons = [
            [
                InlineKeyboardButton(
                    "< 返回", callback_data=f"res:{tmdb_id}:{media_type}"
                )
            ]
        ]
        await query.edit_message_text(
            f"<b>{escape(title)}</b> - 未找到磁力资源",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    total_pages = (len(resources) + RESOURCE_PAGE_SIZE - 1) // RESOURCE_PAGE_SIZE
    page = max(1, min(page, total_pages))
    start = (page - 1) * RESOURCE_PAGE_SIZE
    page_items = resources[start : start + RESOURCE_PAGE_SIZE]

    lines = [f"<b>{escape(title)}</b> - 磁力资源 ({len(resources)}个)\n"]
    buttons = []
    for i, res in enumerate(page_items):
        global_idx = start + i
        res_name = escape(str(res["name"])[:40])
        size = f" [{res['size']}]" if res.get("size") else ""
        quality = f" {res['quality']}" if res.get("quality") else ""
        lines.append(f"{global_idx + 1}. {res_name}{quality}{size}")
        buttons.append(
            [
                InlineKeyboardButton(
                    f"离线 {global_idx + 1}: {str(res['name'])[:25]}",
                    callback_data=f"ol:{global_idx}",
                )
            ]
        )

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("< 上页", callback_data=f"rmagp:{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("下页 >", callback_data=f"rmagp:{page + 1}"))
    buttons.append(nav)
    buttons.append(
        [InlineKeyboardButton("< 返回", callback_data=f"res:{tmdb_id}:{media_type}")]
    )

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ── Save / Offline Actions ────────────────────────────────


async def _save_115_resource(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    idx: int,
):
    query = update.callback_query
    resources = context.user_data.get("cached_115_resources") or []

    if idx >= len(resources):
        await query.edit_message_text("资源索引无效，请重新搜索。")
        return

    res = resources[idx]
    share_link = res.get("share_link", "")
    title = res.get("title", "未知")

    if not share_link:
        await query.edit_message_text("该资源没有分享链接。")
        return

    await query.edit_message_text(f"正在转存: {escape(title[:50])} ...")

    try:
        from app.services.pan115_service import pan115_service
        from app.services.runtime_settings_service import runtime_settings_service

        # Try to determine folder name from detail context
        detail = context.user_data.get("current_detail") or {}
        folder_name = detail.get("title") or title
        if detail.get("year"):
            folder_name = f"{folder_name} ({detail['year']})"

        default_folder = runtime_settings_service.get_pan115_default_folder()
        parent_id = default_folder["folder_id"]

        result = await pan115_service.save_share_to_folder(
            share_url=share_link,
            folder_name=folder_name,
            parent_id=parent_id,
        )

        state = result.get("state", False) if isinstance(result, dict) else False
        if state or (isinstance(result, dict) and not result.get("error")):
            text = f"转存成功: <b>{escape(title[:50])}</b>"
        else:
            error = (
                result.get("error", "未知错误")
                if isinstance(result, dict)
                else str(result)
            )
            text = f"转存失败: {escape(str(error)[:200])}"
    except Exception as e:
        text = f"转存出错: {escape(str(e)[:200])}"

    tmdb_id = context.user_data.get("cached_115_tmdb_id", 0)
    media_type = context.user_data.get("cached_115_media_type", "movie")
    buttons = [
        [
            InlineKeyboardButton(
                "< 返回资源列表", callback_data=f"r115:{tmdb_id}:{media_type}"
            )
        ]
    ]

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _add_offline_task(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    idx: int,
):
    query = update.callback_query
    resources = context.user_data.get("cached_magnet_resources") or []

    if idx >= len(resources):
        await query.edit_message_text("资源索引无效，请重新搜索。")
        return

    res = resources[idx]
    magnet = res.get("magnet", "")
    name = res.get("name", "未知")

    if not magnet:
        await query.edit_message_text("该资源没有磁力链接。")
        return

    await query.edit_message_text(f"正在添加离线任务: {escape(name[:50])} ...")

    try:
        from app.services.pan115_service import pan115_service
        from app.services.runtime_settings_service import runtime_settings_service

        offline_folder = runtime_settings_service.get_pan115_offline_folder()
        wp_path_id = offline_folder["folder_id"]

        result = await pan115_service.offline_task_add(
            url=magnet, wp_path_id=wp_path_id
        )

        if isinstance(result, dict) and result.get("state", False):
            text = f"离线任务已添加: <b>{escape(name[:50])}</b>"
        else:
            error = (
                result.get("error_msg") or result.get("error") or "未知错误"
                if isinstance(result, dict)
                else str(result)
            )
            text = f"添加失败: {escape(str(error)[:200])}"
    except Exception as e:
        text = f"添加出错: {escape(str(e)[:200])}"

    tmdb_id = context.user_data.get("cached_magnet_tmdb_id", 0)
    media_type = context.user_data.get("cached_magnet_media_type", "movie")
    buttons = [
        [
            InlineKeyboardButton(
                "< 返回资源列表", callback_data=f"rmag:{tmdb_id}:{media_type}"
            )
        ]
    ]

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ── Subscriptions ─────────────────────────────────────────


async def _add_subscription(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    tmdb_id: int,
    media_type: str,
):
    query = update.callback_query
    detail = context.user_data.get("current_detail") or {}
    title = detail.get("title", "未知")

    try:
        from app.core.database import async_session_maker
        from sqlalchemy import select
        from app.models.models import Subscription, MediaType as MT

        mt = MT.MOVIE if media_type == "movie" else MT.TV

        async with async_session_maker() as db:
            existing = await db.execute(
                select(Subscription).where(
                    Subscription.tmdb_id == tmdb_id,
                    Subscription.media_type == mt,
                )
            )
            if existing.scalar_one_or_none():
                await query.answer("已订阅该影视", show_alert=True)
                return

            sub = Subscription(
                tmdb_id=tmdb_id,
                title=title,
                media_type=mt,
                poster_path=detail.get("poster_path"),
                overview=(detail.get("overview") or "")[:500],
                year=detail.get("year"),
                rating=detail.get("rating"),
                is_active=True,
                auto_download=True,
            )
            db.add(sub)
            await db.commit()
            await db.refresh(sub)

        await query.answer(f"已订阅: {title}", show_alert=True)

        # Send notification
        from .notifications import tg_bot_notify

        await tg_bot_notify(
            f"<b>新增订阅</b>\n"
            f"{'电影' if media_type == 'movie' else '电视剧'}: {escape(title)}"
        )
    except Exception as e:
        logger.exception("Failed to add subscription")
        await query.answer(f"订阅失败: {str(e)[:100]}", show_alert=True)


async def _delete_subscription(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    sub_id: int,
):
    query = update.callback_query

    try:
        from app.core.database import async_session_maker
        from sqlalchemy import select, delete
        from app.models.models import Subscription, DownloadRecord

        async with async_session_maker() as db:
            result = await db.execute(
                select(Subscription).where(Subscription.id == sub_id)
            )
            sub = result.scalar_one_or_none()
            if not sub:
                await query.answer("订阅不存在", show_alert=True)
                return

            title = sub.title
            await db.execute(
                delete(DownloadRecord).where(DownloadRecord.subscription_id == sub_id)
            )
            await db.execute(delete(Subscription).where(Subscription.id == sub_id))
            await db.commit()

        await query.answer(f"已取消订阅: {title}", show_alert=True)
        await _show_subscriptions(update, context, page=1, edit=True)
    except Exception as e:
        logger.exception("Failed to delete subscription")
        await query.answer(f"取消失败: {str(e)[:100]}", show_alert=True)


async def _show_subscriptions(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    page: int = 1,
    edit: bool = False,
):
    try:
        from app.core.database import async_session_maker
        from sqlalchemy import select
        from app.models.models import Subscription

        async with async_session_maker() as db:
            result = await db.execute(
                select(Subscription)
                .where(Subscription.is_active == True)
                .order_by(Subscription.created_at.desc())
            )
            subs = result.scalars().all()
    except Exception as e:
        text = f"获取订阅列表失败: {escape(str(e))}"
        if edit:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return

    if not subs:
        text = "当前没有活跃的订阅。\n使用 /s <关键词> 搜索影视并添加订阅。"
        if edit:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return

    total_pages = (len(subs) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    page = max(1, min(page, total_pages))
    start = (page - 1) * ITEMS_PER_PAGE
    page_items = subs[start : start + ITEMS_PER_PAGE]

    lines = [f"<b>订阅列表</b> ({len(subs)} 部)\n"]
    buttons = []
    for i, sub in enumerate(page_items):
        type_label = "movie" if sub.media_type.value == "movie" else "tv"
        year_str = f" ({sub.year})" if sub.year else ""
        lines.append(f"{start + i + 1}. [{type_label}] {escape(sub.title)}{year_str}")
        buttons.append(
            [
                InlineKeyboardButton(
                    f"取消订阅: {sub.title[:25]}",
                    callback_data=f"unsub:{sub.id}",
                )
            ]
        )

    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("< 上一页", callback_data=f"subp:{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton("下一页 >", callback_data=f"subp:{page + 1}"))
    if nav:
        buttons.append(nav)

    markup = InlineKeyboardMarkup(buttons)
    text = "\n".join(lines)

    if edit:
        await update.callback_query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup
        )
    else:
        await update.message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup
        )


# ── Helpers ───────────────────────────────────────────────


def _build_search_keywords(detail: dict, media_type: str) -> list[str]:
    title = detail.get("title") or detail.get("name") or ""
    original_title = detail.get("original_title") or detail.get("original_name") or ""
    date_str = detail.get("release_date") or detail.get("first_air_date") or ""
    year = date_str[:4] if date_str else ""

    keywords = []
    if title and year:
        keywords.append(f"{title} {year}")
    if title:
        keywords.append(title)
    if original_title and original_title != title:
        if year:
            keywords.append(f"{original_title} {year}")
        keywords.append(original_title)
    return keywords
