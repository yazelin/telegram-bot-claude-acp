"""
Main bot module for Telegram Claude Bot.
"""

import json
import logging
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application

from .claude import ClaudeSessionManager
from .config import get_config
from .handlers import (
    register_callback_handlers,
    register_command_handlers,
    register_message_handlers,
)
from .handlers.commands import build_model_switch_row
from .state import state_manager
from .utils import (
    download_image_from_url,
    extract_image_urls,
    extract_local_image_paths,
    split_long_message,
)

logger = logging.getLogger(__name__)

# Global session manager
_session_manager: ClaudeSessionManager | None = None

# Nanobanana tool names that generate images
NANOBANANA_TOOLS = {
    "mcp__nanobanana__generate_image",
    "mcp__nanobanana__edit_image",
    "mcp__nanobanana__restore_image",
    "mcp__nanobanana__generate_icon",
    "mcp__nanobanana__generate_pattern",
    "mcp__nanobanana__generate_story",
    "mcp__nanobanana__generate_diagram",
}


def extract_images_from_tool_outputs(tool_status_lines: list) -> list[str]:
    """Extract image paths from nanobanana tool outputs."""
    image_paths = []

    for tool in tool_status_lines:
        name = tool.get("name", "")
        output = tool.get("output")

        output_preview = str(output)[:500] if output else None
        logger.info(f"Checking tool: name={name}, output={output_preview}")

        # Check if it's a nanobanana tool
        is_nanobanana = any(nb_tool in name for nb_tool in NANOBANANA_TOOLS)
        if not is_nanobanana or not output:
            logger.info(f"Skipping tool: is_nanobanana={is_nanobanana}, has_output={bool(output)}")
            continue

        # Parse output - nanobanana returns JSON with generatedFiles
        try:
            # Output might be a string or already parsed
            if isinstance(output, str):
                data = json.loads(output)
            elif isinstance(output, list):
                # Sometimes output is [{"text": "...", "type": "text"}]
                for item in output:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text = item.get("text", "")
                        try:
                            data = json.loads(text)
                            if "generatedFiles" in data:
                                image_paths.extend(data["generatedFiles"])
                        except (json.JSONDecodeError, TypeError):
                            pass
                continue
            else:
                data = output

            # Handle nested result wrapper: {"result": "{...json...}"}
            if isinstance(data, dict) and "result" in data:
                result_str = data["result"]
                if isinstance(result_str, str):
                    try:
                        data = json.loads(result_str)
                    except (json.JSONDecodeError, TypeError):
                        pass

            if isinstance(data, dict) and "generatedFiles" in data:
                image_paths.extend(data["generatedFiles"])

        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"Failed to parse tool output: {e}")

    logger.info(f"Extracted image paths: {image_paths}")
    return image_paths


def get_session_manager() -> ClaudeSessionManager:
    """Get the global session manager."""
    if _session_manager is None:
        raise RuntimeError("Session manager not initialized")
    return _session_manager


async def on_text(chat_id: int, text: str) -> None:
    """Handle streaming text from Claude."""
    state = state_manager.get(chat_id)
    if not state:
        return

    # Accumulate text
    state.text_buffer += text

    # We'll send the complete response on completion
    # For now, just log it
    logger.debug(f"Received text chunk for chat {chat_id}: {text[:50]}...")


def _format_tool_input(input_data: dict) -> str:
    """Format tool input parameters for display (truncated)."""
    if not input_data:
        return ""
    items = list(input_data.items())[:2]
    parts = []
    for k, v in items:
        v_str = repr(v)
        if len(v_str) > 30:
            v_str = v_str[:27] + "..."
        parts.append(f"{k}={v_str}")
    result = ", ".join(parts)
    if len(input_data) > 2:
        result += ", ..."
    return f"({result})"


async def on_tool_start(chat_id: int, tool_id: str, name: str, input_data: dict) -> None:
    """Handle tool execution start."""
    import time
    state = state_manager.get(chat_id)
    if not state:
        return

    session_manager = get_session_manager()
    bot = session_manager.bot

    # Format input params
    input_str = _format_tool_input(input_data)

    # Add tool to status lines with start time
    state.tool_status_lines.append({
        "tool_id": tool_id,
        "name": name,
        "input_str": input_str,
        "status": "running",
        "start_time": time.time(),
    })

    # Build consolidated message
    lines = ["🤖 AI 處理中\n"]
    for tool in state.tool_status_lines:
        display = f"🔧 {tool['name']}"
        if tool.get("input_str"):
            display += f" {tool['input_str']}"
        if tool["status"] == "running":
            display += " ⏳ 執行中..."
        elif tool["status"] == "error":
            display += " ❌ 失敗"
        else:
            duration = tool.get("duration_str", "")
            display += f" ✅ 完成{' (' + duration + ')' if duration else ''}"
        lines.append(display)

    text = "\n".join(lines)

    # Send or edit message
    try:
        if state.tool_notify_message_id:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=state.tool_notify_message_id,
                text=text,
            )
        else:
            msg = await bot.send_message(chat_id, text)
            state.tool_notify_message_id = msg.message_id
    except Exception as e:
        logger.warning(f"Failed to update tool notification: {e}")

    logger.info(f"Tool started: {name}")


async def on_tool_end(chat_id: int, tool_id: str, status: str, output: any) -> None:
    """Handle tool execution end."""
    import time
    state = state_manager.get(chat_id)
    if not state:
        return

    session_manager = get_session_manager()
    bot = session_manager.bot

    # Update tool status with duration and store output
    for tool in state.tool_status_lines:
        if tool["tool_id"] == tool_id:
            tool["status"] = "done" if status == "completed" else "error"
            tool["output"] = output  # Store output for image extraction
            # Calculate duration
            start_time = tool.get("start_time", 0)
            if start_time:
                duration_ms = int((time.time() - start_time) * 1000)
                if duration_ms < 1000:
                    tool["duration_str"] = f"{duration_ms}ms"
                else:
                    tool["duration_str"] = f"{duration_ms/1000:.1f}s"
            break

    # Build consolidated message
    lines = ["🤖 AI 處理中\n"]
    for tool in state.tool_status_lines:
        display = f"🔧 {tool['name']}"
        if tool.get("input_str"):
            display += f" {tool['input_str']}"
        if tool["status"] == "running":
            display += " ⏳ 執行中..."
        elif tool["status"] == "error":
            display += " ❌ 失敗"
        else:
            duration = tool.get("duration_str", "")
            display += f" ✅ 完成{' (' + duration + ')' if duration else ''}"
        lines.append(display)

    text = "\n".join(lines)

    # Edit message
    try:
        if state.tool_notify_message_id:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=state.tool_notify_message_id,
                text=text,
            )
    except Exception as e:
        logger.warning(f"Failed to update tool notification: {e}")

    logger.info(f"Tool ended: status={status}")


async def on_complete(chat_id: int) -> None:
    """Handle query completion."""
    state = state_manager.get(chat_id)
    if not state:
        return

    # Clear busy flag immediately so queue can be processed
    state.busy = False
    state.current_prompt = None

    session_manager = get_session_manager()
    bot = session_manager.bot

    # Extract images from tool outputs BEFORE clearing tool_status_lines
    tool_images = extract_images_from_tool_outputs(state.tool_status_lines)
    if tool_images:
        logger.info(f"Extracted {len(tool_images)} images from tool outputs: {tool_images}")

    # Delete tool notification message
    if state.tool_notify_message_id:
        try:
            await bot.delete_message(chat_id, state.tool_notify_message_id)
        except Exception as e:
            logger.warning(f"Failed to delete tool notification: {e}")
        state.tool_notify_message_id = None
        state.tool_status_lines = []

    # Send accumulated text if any
    if state.text_buffer:
        emoji = state.emoji or "🤖"
        dir_name = Path(state.cwd).name if state.cwd else ""
        header = f"{emoji} Claude ∙ {dir_name}" if dir_name else f"{emoji} Claude"

        response_text = state.text_buffer
        all_images = []

        # 1. Priority: Images from nanobanana tool outputs
        all_images.extend(tool_images)

        # 2. Check for local image paths mentioned in text
        if not all_images:
            all_images.extend(extract_local_image_paths(response_text))

        # Deduplicate while preserving order
        all_images = list(dict.fromkeys(all_images))

        # Send local images
        for img_path in all_images[:5]:  # Max 5 images
            try:
                with open(img_path, "rb") as img_file:
                    await bot.send_photo(chat_id, photo=img_file)
                logger.info(f"Sent local image: {img_path}")
            except Exception as e:
                logger.warning(f"Failed to send local image {img_path}: {e}")

        # 3. Check for image URLs (from web search) - only if no local images
        if not all_images:
            image_urls = extract_image_urls(response_text)
            for url in image_urls[:5]:  # Max 5 images
                local_path = await download_image_from_url(url)
                if local_path:
                    try:
                        with open(local_path, "rb") as img_file:
                            await bot.send_photo(chat_id, photo=img_file)
                        logger.info(f"Sent downloaded image: {url}")
                    except Exception as e:
                        logger.warning(f"Failed to send downloaded image {url}: {e}")

        # Send text response
        full_text = f"{header}\n\n{response_text}"

        # Split long messages
        chunks = split_long_message(full_text)
        for i, chunk in enumerate(chunks):
            reply_to = state.original_message_id if i == 0 else None
            try:
                await bot.send_message(chat_id, chunk, reply_to_message_id=reply_to)
            except Exception as e:
                logger.error(f"Error sending message: {e}")

        state.text_buffer = ""

    # Show completion status - update in place
    if not state.queue:
        dir_name = Path(state.cwd).name if state.cwd else "未設定"
        model_short = state.model.capitalize() if state.model else "未設定"

        status_text = (
            f"🟢 已完成 ∙ 輪次 {state.turn_count}\n"
            f"📂 {dir_name} ∙ 🧠 {model_short}"
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
            except Exception as e:
                logger.debug(f"Could not edit status: {e}")
                msg = await bot.send_message(chat_id, status_text, reply_markup=keyboard)
                state.status_message_id = msg.message_id
        else:
            msg = await bot.send_message(chat_id, status_text, reply_markup=keyboard)
            state.status_message_id = msg.message_id
    else:
        # Update status to show queue processing
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
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=state.status_message_id,
                    text=status_text,
                    reply_markup=keyboard,
                )
            except Exception as e:
                logger.debug(f"Could not edit queue status: {e}")

        # Process next in queue
        await session_manager.process_queue(chat_id, state)

    logger.info(f"Query completed for chat {chat_id}")


async def on_error(chat_id: int, error: Exception) -> None:
    """Handle errors."""
    state = state_manager.get(chat_id)
    session_manager = get_session_manager()
    bot = session_manager.bot

    logger.error(f"Error for chat {chat_id}: {error}")

    await bot.send_message(chat_id, f"❗ 發生錯誤：{error}")

    if state:
        state.busy = False
        state.current_prompt = None


async def post_init(application: Application) -> None:
    """Post-initialization callback."""
    global _session_manager

    # Create session manager
    _session_manager = ClaudeSessionManager(
        bot=application.bot,
        on_text=on_text,
        on_tool_start=on_tool_start,
        on_tool_end=on_tool_end,
        on_complete=on_complete,
        on_error=on_error,
    )

    config = get_config()

    # Send welcome message to admin if configured
    if config.admin_user_id:
        try:
            from datetime import datetime
            restart_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📂 選取專案", callback_data="cmd_dirs"),
                    InlineKeyboardButton("🧠 切換模型", callback_data="cmd_model"),
                ],
            ])

            await application.bot.send_message(
                config.admin_user_id,
                f"🤖 Claude Telegram Bot 已啟動！\n"
                f"⏰ 啟動時間：{restart_time}\n\n"
                f"使用 /help 查看可用命令。",
                reply_markup=keyboard,
            )
            logger.info(f"Welcome message sent to admin: {config.admin_user_id}")
        except Exception as e:
            logger.error(f"Failed to send welcome message: {e}")


async def post_shutdown(application: Application) -> None:
    """Post-shutdown callback."""
    logger.info("Bot shutting down...")

    # Clean up all sessions
    for chat_id, state in state_manager.all_states().items():
        if state.client:
            try:
                # ClaudeClient doesn't need explicit cleanup
                pass
            except Exception as e:
                logger.warning(f"Error cleaning up session {chat_id}: {e}")


def create_application() -> Application:
    """Create and configure the Telegram bot application."""
    config = get_config()

    # Build application with concurrent updates enabled
    application = (
        Application.builder()
        .token(config.telegram_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .concurrent_updates(True)
        .build()
    )

    # Register handlers
    register_command_handlers(application)
    register_callback_handlers(application)
    register_message_handlers(application)

    return application


def run_bot() -> None:
    """Run the Telegram bot."""
    # Configure logging
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )

    logger.info("Starting Claude Telegram Bot...")

    application = create_application()
    application.run_polling(allowed_updates=Update.ALL_TYPES)
