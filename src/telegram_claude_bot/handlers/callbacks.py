"""
Callback query handlers for inline keyboard buttons.
"""

import logging
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from ..config import AVAILABLE_MODELS, get_config, get_model_short_name
from ..state import state_manager
from ..utils import add_to_recent_models, expand_directory_patterns
from .commands import (
    build_model_switch_row,
    is_authorized,
    send_not_authorized_message,
    send_status_message,
    send_welcome_message,
)

logger = logging.getLogger(__name__)


async def switch_model(update: Update, context: ContextTypes.DEFAULT_TYPE, index: int) -> None:
    """Switch to a model by index (called from /model command)."""
    chat_id = update.effective_chat.id
    config = get_config()
    state = state_manager.get_or_create(chat_id, config.default_model)
    bot = context.bot

    if index < 0 or index >= len(AVAILABLE_MODELS):
        if update.message:
            await update.message.reply_text("無效的模型編號")
        return

    selected_model = AVAILABLE_MODELS[index]
    short_name = get_model_short_name(selected_model)
    old_model = state.model

    # Record old model to recent models
    if old_model and old_model != selected_model:
        state.recent_models = add_to_recent_models(state.recent_models, old_model)

    state.model = selected_model

    # If session is active, restart with new model
    if state.session_id and state.cwd:
        dir_name = Path(state.cwd).name
        try:
            from ..bot import get_session_manager
            session_manager = get_session_manager()
            await session_manager.start_session(chat_id, state, state.cwd)
        except Exception as e:
            logger.error(f"Error restarting session with new model: {e}")
            await bot.send_message(chat_id, f"❗ 切換模型失敗：{e}")
            return

        status_text = (
            f"🟢 已切換模型 ∙ 輪次 {state.turn_count}\n"
            f"📂 {dir_name} ∙ 🧠 {short_name}"
        )
    else:
        dir_name = Path(state.cwd).name if state.cwd else "未設定"
        status_text = (
            f"🔵 模型已更新\n"
            f"📂 {dir_name} ∙ 🧠 {short_name}"
        )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📂 專案", callback_data="cmd_dirs"),
         *build_model_switch_row(chat_id, state.model),
         InlineKeyboardButton("🔄 重新開始", callback_data="cmd_reset")],
    ])

    # Try to edit existing status message, otherwise send new
    if state.status_message_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=state.status_message_id,
                text=status_text,
                reply_markup=keyboard,
            )
            return
        except Exception as e:
            logger.debug(f"Could not edit status: {e}")

    msg = await bot.send_message(chat_id, status_text, reply_markup=keyboard)
    state.status_message_id = msg.message_id


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle callback queries from inline keyboards."""
    query = update.callback_query
    chat_id = update.effective_chat.id

    if not is_authorized(update):
        await query.answer()
        await send_not_authorized_message(update)
        return

    await query.answer()
    data = query.data

    # Command buttons
    if data == "cmd_dirs":
        config = get_config()
        dirs = expand_directory_patterns(config.directory_patterns)

        if not dirs:
            await query.edit_message_text(
                "目前沒有設定任何工作目錄。\n"
                "請設定環境變數 DIRECTORY_PATTERNS 或編輯 directories.json。"
            )
            return

        state = state_manager.get_or_create(chat_id, config.default_model)
        state.available_dirs = dirs

        keyboard_rows = []
        for i in range(0, len(dirs), 2):
            row = [InlineKeyboardButton(Path(dirs[i]).name, callback_data=f"set_dir:{i}")]
            if i + 1 < len(dirs):
                row.append(
                    InlineKeyboardButton(Path(dirs[i + 1]).name, callback_data=f"set_dir:{i + 1}")
                )
            keyboard_rows.append(row)

        keyboard = InlineKeyboardMarkup(keyboard_rows)
        await query.edit_message_text("請選擇工作目錄：", reply_markup=keyboard)

    elif data == "cmd_model":
        config = get_config()
        state = state_manager.get_or_create(chat_id, config.default_model)
        current_model = state.model

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
        await query.edit_message_text(
            f"請選擇 AI 模型（目前：{current_short}）",
            reply_markup=keyboard,
        )

    elif data == "cmd_status":
        # Delete the button message
        try:
            await query.message.delete()
        except Exception:
            pass

        user = update.effective_user
        await send_status_message(
            chat_id,
            context.bot,
            user.first_name if user else None,
            user.last_name if user else None,
            user.username if user else None,
        )

    elif data == "cmd_help":
        # Edit the message to show help
        await query.edit_message_text(
            "歡迎使用 Claude Telegram Bot！\n\n"
            "📋 可用命令：\n"
            "/dirs - 列出可用的工作目錄\n"
            "/model [編號] - 查看或選擇 AI 模型\n"
            "/status 或 /st - 查看目前 session 狀態\n"
            "/reset - 重新啟動目前的 Claude session\n"
            "/shutdown - 關閉 Bot\n"
            "/help - 顯示此說明\n\n"
            "在選擇工作目錄後，直接輸入提示詞，Claude 將開始處理並回應。",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📂 選取專案", callback_data="cmd_dirs"),
                    InlineKeyboardButton("🧠 切換模型", callback_data="cmd_model"),
                ],
            ]),
        )

    elif data == "cmd_reset":
        state = state_manager.get(chat_id)
        if not state or not state.session_id:
            # No session - show welcome
            try:
                await query.message.delete()
            except Exception:
                pass
            await send_welcome_message(chat_id, query.message)
            return

        if not state.cwd:
            try:
                await query.message.delete()
            except Exception:
                pass
            await send_welcome_message(chat_id, query.message)
            return

        state.queue = []
        state.resetting = True
        state.busy = False
        state.turn_count = 0

        # Show loading state - edit in place
        dir_name = Path(state.cwd).name if state.cwd else ""
        model_short = get_model_short_name(state.model) if state.model else "未設定"
        loading_text = f"⚙️ 正在重新啟動...\n📂 {dir_name} ∙ 🧠 {model_short}"

        try:
            await query.edit_message_text(loading_text)
        except Exception:
            pass

        try:
            from ..bot import get_session_manager
            session_manager = get_session_manager()
            await session_manager.reset_session(chat_id, state)

            # Update status in place
            status_text = (
                f"🟢 已重新啟動 ∙ 輪次 {state.turn_count}\n"
                f"📂 {dir_name} ∙ 🧠 {model_short}"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📂 專案", callback_data="cmd_dirs"),
                 *build_model_switch_row(chat_id, state.model),
                 InlineKeyboardButton("🔄 重新開始", callback_data="cmd_reset")],
            ])

            try:
                await query.edit_message_text(status_text, reply_markup=keyboard)
                # Update status_message_id to track this message
                state.status_message_id = query.message.message_id
            except Exception as e:
                logger.debug(f"Could not edit reset status: {e}")

        except Exception as e:
            logger.error(f"Error during reset: {e}")
            state.resetting = False
            await query.edit_message_text(f"❗ 重啟失敗：{e}")

    elif data == "shutdown":
        await query.message.reply_text("🔌 正在關閉 Claude Bot...")
        context.application.stop_running()

    # Directory selection
    elif data.startswith("set_dir:"):
        index_str = data.replace("set_dir:", "")
        try:
            index = int(index_str)
        except ValueError:
            await query.answer("無效的目錄編號")
            return

        config = get_config()
        state = state_manager.get_or_create(chat_id, config.default_model)

        # Get available directories
        dirs = state.available_dirs
        if not dirs:
            dirs = expand_directory_patterns(config.directory_patterns)
            state.available_dirs = dirs

        if not dirs or index < 0 or index >= len(dirs):
            await query.answer("無效的目錄編號")
            return

        selected_dir = dirs[index]
        dir_name = Path(selected_dir).name
        model_short = get_model_short_name(state.model) if state.model else "未設定"
        await query.answer(f"選擇：{dir_name}")

        # Update message to show loading state - edit in place
        await query.edit_message_text(f"⏳ 正在啟動 {dir_name}...")

        try:
            from ..bot import get_session_manager
            session_manager = get_session_manager()
            await session_manager.start_session(chat_id, state, selected_dir)

            # Update status in place (don't delete, just edit)
            status_text = (
                f"🟢 已啟動 ∙ 輪次 {state.turn_count}\n"
                f"📂 {dir_name} ∙ 🧠 {model_short}"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📂 專案", callback_data="cmd_dirs"),
                 *build_model_switch_row(chat_id, state.model),
                 InlineKeyboardButton("🔄 重新開始", callback_data="cmd_reset")],
            ])

            try:
                await query.edit_message_text(status_text, reply_markup=keyboard)
                # Track this message as the status message
                state.status_message_id = query.message.message_id
            except Exception as e:
                logger.debug(f"Could not edit status: {e}")

        except Exception as e:
            logger.error(f"Error starting session: {e}")
            await query.edit_message_text(f"❗ 無法啟動 Claude session：{e}")

    # Model selection
    elif data.startswith("set_model:"):
        index_str = data.replace("set_model:", "")
        try:
            index = int(index_str)
        except ValueError:
            await query.answer("無效的模型編號")
            return

        if 0 <= index < len(AVAILABLE_MODELS):
            selected_model = AVAILABLE_MODELS[index]
            short_name = get_model_short_name(selected_model)
            await query.answer(f"選擇：{short_name}")

            config = get_config()
            state = state_manager.get_or_create(chat_id, config.default_model)
            old_model = state.model

            # Record old model to recent models
            if old_model and old_model != selected_model:
                state.recent_models = add_to_recent_models(state.recent_models, old_model)

            state.model = selected_model

            # If session is active, restart with new model
            if state.session_id and state.cwd:
                dir_name = Path(state.cwd).name
                # Show loading state
                await query.edit_message_text(f"⏳ 正在切換模型至 {short_name}...")

                try:
                    from ..bot import get_session_manager
                    session_manager = get_session_manager()
                    await session_manager.start_session(chat_id, state, state.cwd)
                except Exception as e:
                    logger.error(f"Error restarting session with new model: {e}")
                    await query.edit_message_text(f"❗ 切換模型失敗：{e}")
                    return

                # Update status in place
                status_text = (
                    f"🟢 已切換模型 ∙ 輪次 {state.turn_count}\n"
                    f"📂 {dir_name} ∙ 🧠 {short_name}"
                )
            else:
                # No active session, just update model
                dir_name = Path(state.cwd).name if state.cwd else "未設定"
                status_text = (
                    f"🔵 模型已更新\n"
                    f"📂 {dir_name} ∙ 🧠 {short_name}"
                )

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📂 專案", callback_data="cmd_dirs"),
                 *build_model_switch_row(chat_id, state.model),
                 InlineKeyboardButton("🔄 重新開始", callback_data="cmd_reset")],
            ])

            try:
                await query.edit_message_text(status_text, reply_markup=keyboard)
                state.status_message_id = query.message.message_id
            except Exception as e:
                logger.debug(f"Could not edit model status: {e}")
        else:
            await query.answer("無效")



def register_callback_handlers(application) -> None:
    """Register callback query handlers."""
    application.add_handler(CallbackQueryHandler(handle_callback))
