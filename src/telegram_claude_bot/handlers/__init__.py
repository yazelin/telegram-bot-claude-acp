"""
Telegram bot handlers.
"""

from .callbacks import register_callback_handlers
from .commands import register_command_handlers
from .messages import register_message_handlers

__all__ = [
    "register_command_handlers",
    "register_callback_handlers",
    "register_message_handlers",
]
