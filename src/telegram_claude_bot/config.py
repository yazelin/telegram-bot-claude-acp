"""
Configuration management for Telegram Claude Bot.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env file if present
load_dotenv()


@dataclass
class Config:
    """Bot configuration loaded from environment variables."""

    # Required
    telegram_token: str

    # Optional
    directory_patterns: list[str]
    default_model: str

    # Authorization
    allowed_user_ids: list[int]
    admin_user_id: int | None
    allowed_group_ids: list[int]

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")

        # Parse directory patterns
        patterns_str = os.getenv("DIRECTORY_PATTERNS", "")
        patterns = [p.strip() for p in patterns_str.split(",") if p.strip()]

        # If no patterns from env, try directories.json
        if not patterns:
            patterns = cls._load_directories_json()

        # Parse allowed user IDs
        allowed_users_str = os.getenv("ALLOWED_USER_IDS", "")
        allowed_user_ids = [
            int(uid.strip())
            for uid in allowed_users_str.split(",")
            if uid.strip().lstrip("-").isdigit()
        ]

        # Parse admin user ID
        admin_str = os.getenv("ADMIN_USER_ID", "")
        admin_user_id = int(admin_str) if admin_str.strip().lstrip("-").isdigit() else None

        # Parse allowed group IDs
        allowed_groups_str = os.getenv("ALLOWED_GROUP_IDS", "")
        allowed_group_ids = [
            int(gid.strip())
            for gid in allowed_groups_str.split(",")
            if gid.strip().lstrip("-").isdigit()
        ]

        return cls(
            telegram_token=token,
            directory_patterns=patterns,
            default_model=os.getenv("DEFAULT_MODEL", "sonnet"),
            allowed_user_ids=allowed_user_ids,
            admin_user_id=admin_user_id,
            allowed_group_ids=allowed_group_ids,
        )

    def is_authorized(self, user_id: int | None, chat_id: int, is_mentioned: bool = False) -> bool:
        """
        Check if a user/chat is authorized to use the bot.

        Args:
            user_id: The user ID (can be None for anonymous)
            chat_id: The chat ID
            is_mentioned: Whether the bot was mentioned (required for groups)

        Returns:
            True if authorized
        """
        # Admin always allowed
        if user_id and self.admin_user_id and user_id == self.admin_user_id:
            return True

        # Check if it's a group chat (negative ID)
        if chat_id < 0:
            # Group chat - need to be in allowed groups and be mentioned
            if not self.allowed_group_ids:
                return False
            if chat_id not in self.allowed_group_ids:
                return False
            # In groups, bot must be mentioned
            return is_mentioned

        # Private chat - check allowed users
        if not self.allowed_user_ids:
            # No restrictions, allow all
            return True

        return user_id in self.allowed_user_ids

    @staticmethod
    def _load_directories_json() -> list[str]:
        """Load directory patterns from directories.json if it exists."""
        import json

        json_path = Path(__file__).parent.parent.parent.parent / "directories.json"
        try:
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [str(p) for p in data]
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return []


# Singleton config instance
_config: Config | None = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = Config.from_env()
    return _config


# Available models (Claude models only since we use Claude CLI)
AVAILABLE_MODELS = [
    "opus",
    "sonnet",
    "haiku",
]


def get_model_short_name(model: str) -> str:
    """Get a short display name for a model."""
    return model.capitalize()

# Session emojis for visual distinction
SESSION_EMOJIS = [
    "🔵", "🟢", "🔴", "🟣", "🟡", "🟠",
    "✨", "🔥", "🌟", "🚀", "🧠", "🔔",
    "🎯", "✅", "⚡️", "🌈", "🍀", "💎",
]
