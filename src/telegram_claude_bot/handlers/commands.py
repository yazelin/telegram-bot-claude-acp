"""
Command handlers for the Telegram bot.
"""

import logging
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CommandHandler, ContextTypes

from ..config import AVAILABLE_MODELS, get_config, get_model_short_name
from ..state import state_manager
from ..utils import expand_directory_patterns, format_chat_target

logger = logging.getLogger(__name__)


def is_authorized(update: Update) -> bool:
    """Check if the user/chat is authorized to use the bot."""
    config = get_config()
    user_id = update.effective_user.id if update.effective_user else None
    chat_id = update.effective_chat.id

    # Check if bot is mentioned (for group chats)
    is_mentioned = False
    if update.message and update.message.entities:
        bot_username = update.get_bot().username
        for entity in update.message.entities:
            if entity.type == "mention":
                mention_text = update.message.text[entity.offset:entity.offset + entity.length]
                if bot_username and mention_text.lower() == f"@{bot_username.lower()}":
                    is_mentioned = True
                    break

    return config.is_authorized(user_id, chat_id, is_mentioned)


async def send_not_authorized_message(update: Update) -> None:
    """Send rejection message to unauthorized users."""
    await update.message.reply_text(
        "🙇 非常抱歉，您沒有使用此機器人的權限。\n"
        "如有需要，請聯繫機器人的管理員。感謝您的理解！"
    )


def build_model_switch_row(chat_id: int, current_model: str | None) -> list[InlineKeyboardButton]:
    """Build inline keyboard row with model switch buttons."""
    row = [InlineKeyboardButton("🧠 切換模型", callback_data="cmd_model")]

    state = state_manager.get(chat_id)
    if state and state.recent_models:
        for model in state.recent_models[:2]:
            if model != current_model and model in AVAILABLE_MODELS:
                idx = AVAILABLE_MODELS.index(model)
                short_name = get_model_short_name(model)
                row.append(
                    InlineKeyboardButton(f"⚡{short_name}", callback_data=f"set_model:{idx}")
                )

    return row


async def send_welcome_message(chat_id: int, message_target) -> None:
    """Send welcome/help message to a chat. Works with both commands and callbacks."""
    state = state_manager.get(chat_id)
    current_model = state.model if state else get_config().default_model

    instructions = (
        "歡迎使用 Claude Telegram Bot！\n\n"
        "📋 可用命令：\n"
        "/dirs - 列出可用的工作目錄\n"
        "/model [編號] - 查看或選擇 AI 模型\n"
        "/status 或 /st - 查看目前 session 狀態\n"
        "/reset - 重新啟動目前的 Claude session\n"
        "/shutdown - 關閉 Bot\n"
        "/help - 顯示此說明\n\n"
        "在選擇工作目錄後，直接輸入提示詞，Claude 將開始處理並回應。\n"
        "若目前有任務在進行中，新的提示詞將排入隊列。"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📂 選取專案", callback_data="cmd_dirs"),
            *build_model_switch_row(chat_id, current_model),
        ],
    ])

    await message_target.reply_text(instructions, reply_markup=keyboard)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start and /help commands."""
    chat_id = update.effective_chat.id

    if not is_authorized(update):
        await send_not_authorized_message(update)
        return

    await send_welcome_message(chat_id, update.message)


async def cmd_dirs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /dirs command - list available directories."""
    chat_id = update.effective_chat.id

    if not is_authorized(update):
        await send_not_authorized_message(update)
        return

    config = get_config()
    dirs = expand_directory_patterns(config.directory_patterns)

    if not dirs:
        await update.message.reply_text(
            "目前沒有設定任何工作目錄。\n"
            "請設定環境變數 DIRECTORY_PATTERNS 或編輯 directories.json。"
        )
        return

    # Store available dirs in state
    state = state_manager.get_or_create(chat_id, config.default_model)
    state.available_dirs = dirs

    # Build keyboard (2 buttons per row)
    keyboard_rows = []
    for i in range(0, len(dirs), 2):
        row = [InlineKeyboardButton(Path(dirs[i]).name, callback_data=f"set_dir:{i}")]
        if i + 1 < len(dirs):
            row.append(
                InlineKeyboardButton(Path(dirs[i + 1]).name, callback_data=f"set_dir:{i + 1}")
            )
        keyboard_rows.append(row)

    keyboard = InlineKeyboardMarkup(keyboard_rows)
    await update.message.reply_text("請選擇工作目錄：", reply_markup=keyboard)


async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /model command - list or select model."""
    chat_id = update.effective_chat.id

    if not is_authorized(update):
        await send_not_authorized_message(update)
        return

    config = get_config()
    state = state_manager.get_or_create(chat_id, config.default_model)
    current_model = state.model

    # Check if an index was provided
    args = context.args
    if args and args[0].isdigit():
        index = int(args[0]) - 1
        if 0 <= index < len(AVAILABLE_MODELS):
            # Import here to avoid circular import
            from .callbacks import switch_model
            await switch_model(update, context, index)
            return
        else:
            await update.message.reply_text("無效的模型編號。請使用 /model 查看可用模型。")
            return

    # Show model list
    lines = []
    for i, model in enumerate(AVAILABLE_MODELS):
        marker = "✓ " if model == current_model else "  "
        short_name = get_model_short_name(model)
        lines.append(f"{marker}{i + 1}. {short_name}")

    # Build keyboard (2 buttons per row)
    keyboard_rows = []
    for i in range(0, len(AVAILABLE_MODELS), 2):
        model1 = AVAILABLE_MODELS[i]
        short1 = get_model_short_name(model1)
        prefix1 = "✓ " if model1 == current_model else ""
        row = [InlineKeyboardButton(f"{prefix1}{short1}", callback_data=f"set_model:{i}")]

        if i + 1 < len(AVAILABLE_MODELS):
            model2 = AVAILABLE_MODELS[i + 1]
            short2 = get_model_short_name(model2)
            prefix2 = "✓ " if model2 == current_model else ""
            row.append(
                InlineKeyboardButton(f"{prefix2}{short2}", callback_data=f"set_model:{i + 1}")
            )

        keyboard_rows.append(row)

    keyboard = InlineKeyboardMarkup(keyboard_rows)
    current_short = get_model_short_name(current_model)
    text = f"可選擇的 AI 模型：\n{chr(10).join(lines)}\n\n目前使用：{current_short}"
    await update.message.reply_text(text, reply_markup=keyboard)


async def send_status_message(
    chat_id: int,
    bot,  # Bot object for sending/editing messages
    user_first_name: str | None = None,
    user_last_name: str | None = None,
    username: str | None = None,
) -> None:
    """Send or update status bar message. Edits existing if possible."""
    state = state_manager.get(chat_id)
    config = get_config()

    if not state:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📂 選取專案", callback_data="cmd_dirs"),
                *build_model_switch_row(chat_id, config.default_model),
            ],
        ])
        msg = await bot.send_message(
            chat_id,
            "目前沒有任何 chat state，請使用 /dirs 查看並選擇目錄以啟動 session。",
            reply_markup=keyboard,
        )
        return

    # Format status message
    chat_target = format_chat_target(user_first_name, user_last_name, username, chat_id)
    logger.info(
        f"Status: chat={chat_id}, turn={state.turn_count}, "
        f"busy={state.busy}, queue={len(state.queue)}"
    )

    has_session = state.session_id is not None
    activity = "正在運行" if has_session else "未啟動"
    session_id = state.session_id or "未啟動"
    cwd = state.cwd or "未設定"
    busy = "是" if state.busy else "否"
    queue_len = len(state.queue)
    queue_msg = f"等待佇列：{queue_len} 個任務" if queue_len > 0 else "等待佇列：沒有任務"
    reset_msg = "是（將在完成後重新啟動 🔄）" if state.resetting else "否"

    current_task = ""
    if state.busy and state.current_prompt:
        prompt = state.current_prompt
        truncated = prompt[:100] + "..." if len(prompt) > 100 else prompt
        current_task = f"\n\n📝 正在執行的任務：\n{truncated}"

    queue_preview = ""
    if queue_len > 0:
        preview_items = []
        for i, q in enumerate(state.queue[:3]):
            truncated = q[:50] + "..." if len(q) > 50 else q
            preview_items.append(f"  {i + 1}. {truncated}")
        queue_preview = "\n\n📋 等待中的任務：\n" + "\n".join(preview_items)
        if queue_len > 3:
            queue_preview += f"\n  ...還有 {queue_len - 3} 個任務"

    note = "系統目前忙碌，請稍候。" if state.busy else "系統閒置，歡迎送出新指令！"
    model_short = get_model_short_name(state.model) if state.model else "未設定"

    msg_text = f"""🤖 Claude Session 狀態報告

我的主人：{chat_target}
程序狀態：{activity}
工作階段：{session_id}
選用模型：{model_short}
工作目錄：{cwd}
已執行輪次：{state.turn_count}
工作狀態：{busy}
{queue_msg}
正在重啟：{reset_msg}{current_task}{queue_preview}

小提醒：{note}"""

    # Build keyboard - always show all buttons
    row = [
        InlineKeyboardButton("📂 專案", callback_data="cmd_dirs"),
        *build_model_switch_row(chat_id, state.model),
        InlineKeyboardButton("🔄 重啟", callback_data="cmd_reset"),
    ]

    keyboard = InlineKeyboardMarkup([row])

    # Try to edit existing status message, otherwise send new one
    if state.status_message_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=state.status_message_id,
                text=msg_text,
                reply_markup=keyboard,
            )
            return
        except Exception as e:
            logger.debug(f"Could not edit status message: {e}")
            state.status_message_id = None

    # Send new status message
    msg = await bot.send_message(chat_id, msg_text, reply_markup=keyboard)
    state.status_message_id = msg.message_id


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status and /st commands."""
    chat_id = update.effective_chat.id

    if not is_authorized(update):
        await send_not_authorized_message(update)
        return

    user = update.effective_user
    await send_status_message(
        chat_id,
        context.bot,
        user.first_name if user else None,
        user.last_name if user else None,
        user.username if user else None,
    )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /reset command."""
    chat_id = update.effective_chat.id

    if not is_authorized(update):
        await send_not_authorized_message(update)
        return

    state = state_manager.get(chat_id)
    if not state or not state.session_id:
        await update.message.reply_text(
            "目前沒有正在運行的 session。請使用 /dirs 查看並選擇工作目錄。"
        )
        return

    await update.message.reply_text("🔄 正在重新啟動 Claude session...")

    try:
        from ..bot import get_session_manager
        session_manager = get_session_manager()
        await session_manager.reset_session(chat_id, state)

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📂 選取專案", callback_data="cmd_dirs"),
                *build_model_switch_row(chat_id, state.model),
            ],
            [InlineKeyboardButton("🔄 重新開始", callback_data="cmd_reset")],
        ])
        await update.message.reply_text("✅ Session 已重新啟動。", reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Error resetting session: {e}")
        await update.message.reply_text(f"❗ 重設失敗：{e}")


async def cmd_shutdown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /shutdown command."""
    if not is_authorized(update):
        await send_not_authorized_message(update)
        return

    await update.message.reply_text("🔌 正在關閉 Claude Bot...")

    # Stop the application
    context.application.stop_running()


def register_command_handlers(application) -> None:
    """Register all command handlers."""
    application.add_handler(CommandHandler(["start", "help"], cmd_start))
    application.add_handler(CommandHandler("dirs", cmd_dirs))
    application.add_handler(CommandHandler("model", cmd_model))
    application.add_handler(CommandHandler(["status", "st"], cmd_status))
    application.add_handler(CommandHandler("reset", cmd_reset))
    application.add_handler(CommandHandler("shutdown", cmd_shutdown))
