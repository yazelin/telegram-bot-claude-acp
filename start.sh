#!/bin/bash
# Telegram Claude Bot start script

# Kill existing bot processes
pkill -9 -f "telegram_claude_bot" 2>/dev/null
sleep 1

# Start bot with logging
cd /home/ct/SDD/telegram-bot-claude-acp
uv run python -m telegram_claude_bot &> /tmp/tgbot.log &

echo "Bot started. Log: /tmp/tgbot.log"
sleep 3
tail -10 /tmp/tgbot.log
