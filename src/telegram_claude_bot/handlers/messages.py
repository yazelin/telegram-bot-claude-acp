"""
Message handlers for regular text messages.
"""

import logging
import os
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, MessageHandler, filters

from ..config import get_config
from ..state import state_manager
from .commands import build_model_switch_row, is_authorized, send_not_authorized_message

logger = logging.getLogger(__name__)

# Directory to save downloaded images for editing
IMAGE_DOWNLOAD_DIR = "/tmp/telegram-claude-bot/images"


async def download_telegram_photo(bot, photo, filename_prefix: str = "photo") -> str | None:
    """Download a Telegram photo to local file and return the path."""
    try:
        os.makedirs(IMAGE_DOWNLOAD_DIR, exist_ok=True)
        file = await bot.get_file(photo.file_id)

        # Generate local path
        ext = os.path.splitext(file.file_path)[1] if file.file_path else ".jpg"
        filename = f"{filename_prefix}_{photo.file_unique_id}{ext}"
        local_path = os.path.join(IMAGE_DOWNLOAD_DIR, filename)

        # Download the file
        await file.download_to_drive(local_path)
        logger.info(f"Downloaded photo to: {local_path}")
        return local_path
    except Exception as e:
        logger.error(f"Failed to download photo: {e}")
        return None


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle regular text messages (prompts to Claude)."""
    chat_id = update.effective_chat.id
    message = update.message

    if not is_authorized(update):
        await send_not_authorized_message(update)
        return

    # Get text from message or caption
    text = message.text or message.caption

    # Handle reply to a photo message (for editing images)
    reply_image_path = None
    if message.reply_to_message and message.reply_to_message.photo:
        # User is replying to a photo - download it for editing
        replied_photo = message.reply_to_message.photo[-1]  # Get largest
        reply_image_path = await download_telegram_photo(
            context.bot, replied_photo, "reply_img"
        )
        if reply_image_path:
            logger.info(f"Downloaded reply photo: {reply_image_path}")

    # Handle photo attachments
    if message.photo:
        try:
            state = state_manager.get_or_create(chat_id, get_config().default_model)
            # Get the largest photo
            photo = message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            file_url = file.file_path

            state.images.append(file_url)
            await message.reply_text(f"✅ 已將圖片加入參考上下文（共 {len(state.images)} 張）。")

            # If no text, just store the image
            if not text:
                return

        except Exception as e:
            logger.error(f"Error handling photo: {e}")
            await message.reply_text("❗ 處理圖片時發生錯誤（已忽略）。")
            if not text:
                return

    # Handle document (image files)
    is_image_doc = (
        message.document
        and message.document.mime_type
        and message.document.mime_type.startswith("image/")
    )
    if is_image_doc:
        try:
            state = state_manager.get_or_create(chat_id, get_config().default_model)
            file = await context.bot.get_file(message.document.file_id)
            file_url = file.file_path

            state.images.append(file_url)
            await message.reply_text(f"✅ 已將圖片加入參考上下文（共 {len(state.images)} 張）。")

            if not text:
                return

        except Exception as e:
            logger.error(f"Error handling document: {e}")
            await message.reply_text("❗ 處理圖片時發生錯誤（已忽略）。")
            if not text:
                return

    # No text to process
    if not text:
        return

    # Ignore commands (handled by command handlers)
    if text.startswith("/"):
        return

    # Get state
    state = state_manager.get(chat_id)

    if not state or not state.session_id or not state.cwd:
        await message.reply_text("請先用 /dirs 查看並選擇工作目錄。")
        return

    # Check if resetting
    if state.resetting:
        await message.reply_text("⚠️ 正在重新啟動 Claude session，請稍後再試。")
        return

    # Build the prompt, including reply image path if present
    prompt = text
    if reply_image_path:
        prompt = f"{text}\n\n[用戶回覆的圖片路徑: {reply_image_path}]"

    # Queue or send prompt
    if state.busy:
        state.queue.append(prompt)
        logger.info(
            f"Task queued: chat={chat_id}, queue={len(state.queue)}, "
            f"status_msg_id={state.status_message_id}"
        )

        # Update status message in place
        dir_name = Path(state.cwd).name if state.cwd else "未設定"
        model_short = state.model.capitalize() if state.model else "未設定"
        queue_len = len(state.queue)

        status_text = (
            f"🟡 處理中 ∙ 輪次 {state.turn_count} ∙ 佇列 {queue_len}\n"
            f"📂 {dir_name} ∙ 🧠 {model_short}"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📂 專案", callback_data="cmd_dirs"),
             *build_model_switch_row(chat_id, state.model),
             InlineKeyboardButton("🔄 重新開始", callback_data="cmd_reset")],
        ])

        if state.status_message_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=state.status_message_id,
                    text=status_text,
                    reply_markup=keyboard,
                )
                logger.info("Updated status message for queue")
            except Exception as e:
                logger.warning(f"Could not edit status for queue: {e}")
        else:
            logger.warning(f"No status_message_id set for chat {chat_id}")
    else:
        state.original_message_id = message.message_id
        state.busy = True  # Set busy BEFORE calling send_prompt to prevent race condition

        try:
            from ..bot import get_session_manager
            session_manager = get_session_manager()
            await session_manager.send_prompt(chat_id, state, prompt)

        except Exception as e:
            logger.error(f"Error sending prompt: {e}")
            await message.reply_text(f"❗ 發送提示時發生錯誤：{e}")
            state.busy = False
            state.current_prompt = None


def register_message_handlers(application) -> None:
    """Register message handlers."""
    # Handle text messages and photos/documents with captions
    application.add_handler(
        MessageHandler(
            filters.TEXT | filters.PHOTO | filters.Document.IMAGE,
            handle_message,
        )
    )
