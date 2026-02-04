"""
Claude session management using claude-code-acp.
"""

import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from claude_code_acp import ClaudeClient

if TYPE_CHECKING:
    from telegram import Bot

    from ..state import ChatState

logger = logging.getLogger(__name__)


class ClaudeSessionManager:
    """
    Manages Claude sessions for Telegram chats.

    Uses ClaudeClient from claude-code-acp for direct Claude CLI integration.
    """

    def __init__(
        self,
        bot: "Bot",
        on_text: Callable[[int, str], Coroutine[Any, Any, None]],
        on_tool_start: Callable[[int, str, str, dict], Coroutine[Any, Any, None]],
        on_tool_end: Callable[[int, str, str, Any], Coroutine[Any, Any, None]],
        on_complete: Callable[[int], Coroutine[Any, Any, None]],
        on_error: Callable[[int, Exception], Coroutine[Any, Any, None]],
    ):
        """
        Initialize the session manager.

        Args:
            bot: Telegram bot instance for sending messages.
            on_text: Callback for streaming text.
            on_tool_start: Callback for tool execution start.
            on_tool_end: Callback for tool execution end.
            on_complete: Callback for query completion.
            on_error: Callback for errors.
        """
        self.bot = bot
        self._on_text = on_text
        self._on_tool_start = on_tool_start
        self._on_tool_end = on_tool_end
        self._on_complete = on_complete
        self._on_error = on_error

    async def start_session(self, chat_id: int, state: "ChatState", cwd: str) -> None:
        """
        Start a new Claude session for the chat.

        Args:
            chat_id: Telegram chat ID.
            state: Chat state to update.
            cwd: Working directory for the session.
        """
        # Close existing client if any
        if state.client is not None:
            try:
                # ClaudeClient doesn't need explicit close, just replace
                pass
            except Exception as e:
                logger.warning(f"Error closing previous client: {e}")

        # Create new client with MCP servers
        mcp_servers = [
            {
                "name": "nanobanana",
                "type": "stdio",
                "command": "bash",
                "args": [
                    "-c",
                    "set -a && source /home/ct/SDD/telegram-bot-claude-acp/.env "
                    "&& set +a && uvx nanobanana-py",
                ],
            }
        ]

        # System prompt to guide Claude on image handling
        # Use preset + append mode to keep Claude Code abilities
        system_prompt = {
            "type": "preset",
            "preset": "claude_code",
            "append": """

你是一個友善的 Telegram Bot 助手。請用繁體中文回答，保持簡潔有禮。

當用戶要求畫圖、生成圖片時，請使用 mcp__nanobanana__generate_image 工具。

當用戶要求找圖或搜尋圖片時：
1. 用 WebSearch 搜尋圖片，優先找 Unsplash、Pexels、Pixabay 等免費圖庫
2. 避免使用 Wikipedia/Wikimedia 的圖片（會被封鎖下載）
3. 找出直接的圖片檔案 URL（必須以 .jpg/.jpeg/.png/.webp 結尾的直鏈）
4. 把圖片 URL 直接寫在回覆中，系統會自動下載傳送給用戶

當用戶回覆一張圖片並要求修改時，訊息中會包含 [用戶回覆的圖片路徑: /path/to/image.jpg]，
請使用 mcp__nanobanana__edit_image 工具，file 參數使用該路徑。

使用 nanobanana 工具時，resolution 參數固定用 "1K"。"""
        }

        client = ClaudeClient(cwd=cwd, mcp_servers=mcp_servers, system_prompt=system_prompt)

        # Register event handlers
        @client.on_text
        async def handle_text(text: str):
            await self._on_text(chat_id, text)

        @client.on_tool_start
        async def handle_tool_start(tool_id: str, name: str, input_data: dict):
            await self._on_tool_start(chat_id, tool_id, name, input_data)

        @client.on_tool_end
        async def handle_tool_end(tool_id: str, status: str, output: Any):
            await self._on_tool_end(chat_id, tool_id, status, output)

        @client.on_complete
        async def handle_complete():
            await self._on_complete(chat_id)

        @client.on_error
        async def handle_error(error: Exception):
            await self._on_error(chat_id, error)

        @client.on_permission
        async def handle_permission(name: str, input_data: dict) -> bool:
            # Auto-approve all permissions for now
            # TODO: Could forward to user for confirmation
            logger.info(f"Auto-approving permission: {name}")
            return True

        # Start the session
        session_id = await client.start_session()

        # Update state
        state.client = client
        state.session_id = session_id
        state.cwd = cwd
        state.busy = False
        state.queue = []
        state.resetting = False
        state.turn_count = 0
        state.text_buffer = ""

        logger.info(f"Started session {session_id} for chat {chat_id} in {cwd}")

    async def send_prompt(
        self,
        chat_id: int,
        state: "ChatState",
        prompt: str,
    ) -> str:
        """
        Send a prompt to Claude and return the response.

        Args:
            chat_id: Telegram chat ID.
            state: Chat state.
            prompt: The prompt to send.

        Returns:
            The response text.
        """
        if state.client is None:
            raise RuntimeError("No active session")

        state.busy = True
        state.current_prompt = prompt
        state.text_buffer = ""
        state.turn_count += 1
        logger.info(f"Turn count incremented to {state.turn_count} for chat {chat_id}")

        try:
            # Append images if any
            full_prompt = prompt
            if state.images:
                image_list = "\n".join(f"{i+1}. {url}" for i, url in enumerate(state.images))
                full_prompt = f"{prompt}\n\n參考圖片：\n{image_list}"

            response = await state.client.query(full_prompt)
            return response

        finally:
            state.busy = False
            state.current_prompt = None

    async def reset_session(self, chat_id: int, state: "ChatState") -> None:
        """
        Reset the session for a chat.

        Args:
            chat_id: Telegram chat ID.
            state: Chat state to reset.
        """
        state.resetting = True
        state.queue = []
        state.busy = False
        state.current_prompt = None
        state.turn_count = 0
        state.text_buffer = ""

        cwd = state.cwd
        if cwd:
            await self.start_session(chat_id, state, cwd)

        state.resetting = False
        logger.info(f"Reset session for chat {chat_id}")

    async def process_queue(self, chat_id: int, state: "ChatState") -> None:
        """
        Process the next prompt in the queue if any.

        Args:
            chat_id: Telegram chat ID.
            state: Chat state.
        """
        if state.busy or not state.queue or state.resetting:
            return

        next_prompt = state.queue.pop(0)
        try:
            await self.send_prompt(chat_id, state, next_prompt)
        except Exception as e:
            await self._on_error(chat_id, e)
