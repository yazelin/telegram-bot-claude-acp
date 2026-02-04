"""
Telegram Claude Bot - A Telegram bot for Claude CLI using claude-code-acp.
"""

from .bot import create_application, run_bot

__version__ = "0.1.0"

__all__ = [
    "create_application",
    "run_bot",
    "main",
]


def main() -> None:
    """Entry point for the telegram-claude-bot command."""
    run_bot()


if __name__ == "__main__":
    main()
