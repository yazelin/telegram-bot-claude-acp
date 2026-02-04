"""
Chat state management for Telegram Claude Bot.
"""

from dataclasses import dataclass, field

from claude_code_acp import ClaudeClient


@dataclass
class ToolResult:
    """Stored tool execution result for later display."""

    tool_name: str
    full_text: str
    start_msg_id: int | None = None
    params_text: str | None = None


@dataclass
class ChatState:
    """Per-chat conversation state."""

    # Claude client instance
    client: ClaudeClient | None = None

    # Session info
    session_id: str | None = None
    cwd: str | None = None
    model: str = "claude-sonnet-4"

    # Execution state
    busy: bool = False
    queue: list[str] = field(default_factory=list)
    resetting: bool = False

    # Visual identifier
    emoji: str = "🤖"

    # Current prompt being processed
    current_prompt: str | None = None

    # Original message ID for reply
    original_message_id: int | None = None

    # Turn count in this session
    turn_count: int = 0

    # Attached images
    images: list[str] = field(default_factory=list)

    # Tool execution tracking
    tool_results: dict[str, ToolResult] = field(default_factory=dict)
    tool_params: dict[str, ToolResult] = field(default_factory=dict)

    # Recent models used (for quick switch buttons)
    recent_models: list[str] = field(default_factory=list)

    # Available directories (cached for inline keyboard)
    available_dirs: list[str] = field(default_factory=list)

    # Text accumulator for streaming response
    text_buffer: str = ""

    # Status bar message ID (for in-place updates)
    status_message_id: int | None = None

    # Tool notification message ID (for consolidating tool status)
    tool_notify_message_id: int | None = None
    tool_status_lines: list[dict] = field(default_factory=list)


class ChatStateManager:
    """Manages chat states for all chats."""

    def __init__(self):
        self._states: dict[int, ChatState] = {}
        self._used_emojis: set[str] = set()

    def get(self, chat_id: int) -> ChatState | None:
        """Get chat state if exists."""
        return self._states.get(chat_id)

    def get_or_create(self, chat_id: int, default_model: str = "claude-sonnet-4") -> ChatState:
        """Get or create chat state."""
        if chat_id not in self._states:
            from .config import SESSION_EMOJIS

            emoji = self._pick_emoji(SESSION_EMOJIS)
            self._states[chat_id] = ChatState(model=default_model, emoji=emoji)
        return self._states[chat_id]

    def remove(self, chat_id: int) -> None:
        """Remove chat state."""
        state = self._states.pop(chat_id, None)
        if state and state.emoji:
            self._used_emojis.discard(state.emoji)

    def _pick_emoji(self, available: list[str]) -> str:
        """Pick an unused emoji for a new session."""
        for emoji in available:
            if emoji not in self._used_emojis:
                self._used_emojis.add(emoji)
                return emoji
        # Fallback: reuse a random one
        import random
        return random.choice(available)

    def all_states(self) -> dict[int, ChatState]:
        """Get all chat states."""
        return self._states


# Global state manager
state_manager = ChatStateManager()
