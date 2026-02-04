# Telegram Claude Bot

透過 Telegram 操作 Claude CLI 的機器人。使用 [claude-code-acp](https://github.com/yazelin/claude-code-acp-py) 套件與 Claude CLI 整合。

## 功能

- **目錄選擇**：透過 Inline Keyboard 選擇工作目錄
- **提示詞執行**：直接輸入文字發送到 Claude
- **佇列系統**：忙碌時自動排隊新請求
- **模型切換**：支援多種 Claude 模型
- **工具追蹤**：顯示工具執行狀態與結果
- **圖片支援**：可附加圖片作為參考上下文

## 系統需求

- Python 3.10+
- Claude CLI 已安裝並認證 (`claude /login`)
- Telegram Bot Token (從 [@BotFather](https://t.me/botfather) 取得)

## 安裝

```bash
# Clone
git clone https://github.com/yazelin/telegram-bot-claude-acp
cd telegram-bot-claude-acp

# 使用 uv 安裝
uv sync

# 或使用 pip
pip install -e .
```

## 設定

1. 複製 `.env.example` 為 `.env`：

```bash
cp .env.example .env
```

2. 編輯 `.env` 設定環境變數：

```env
# 必填
TELEGRAM_BOT_TOKEN=your_telegram_bot_token

# 選填
DIRECTORY_PATTERNS=/path/to/projects/*,/path/to/libs/**
OWNER_CHAT_ID=123456789
DEFAULT_MODEL=claude-sonnet-4
```

### 環境變數說明

| 變數 | 必填 | 說明 |
|------|------|------|
| `TELEGRAM_BOT_TOKEN` | ✅ | 從 @BotFather 取得的 Bot Token |
| `DIRECTORY_PATTERNS` | ❌ | 目錄 glob 模式，用逗號分隔 |
| `OWNER_CHAT_ID` | ❌ | 限制只有此 Chat ID 可使用 |
| `DEFAULT_MODEL` | ❌ | 預設模型 (預設: claude-sonnet-4) |

## 執行

```bash
# 使用 uv
uv run telegram-claude-bot

# 或直接執行
python -m telegram_claude_bot
```

## 指令

| 指令 | 說明 |
|------|------|
| `/start`, `/help` | 顯示歡迎訊息與使用說明 |
| `/dirs` | 列出可用的工作目錄 |
| `/model [n]` | 查看或選擇 AI 模型 |
| `/status`, `/st` | 查看目前 session 狀態 |
| `/reset` | 重新啟動 Claude session |
| `/shutdown` | 關閉 Bot |

## 使用流程

1. 使用 `/dirs` 選擇工作目錄
2. 直接輸入提示詞，Claude 將處理並回應
3. 若正在處理中，新提示詞會自動排隊
4. 使用 `/reset` 可重新開始 session

## 可用模型

- `claude-sonnet-4` (預設)
- `claude-opus-4`
- `claude-haiku-3.5`

## 架構

```
telegram-bot-claude-acp/
├── src/telegram_claude_bot/
│   ├── __init__.py         # 入口點
│   ├── bot.py              # 主要 bot 邏輯
│   ├── config.py           # 設定管理
│   ├── state.py            # 狀態管理
│   ├── utils.py            # 工具函式
│   ├── handlers/           # Telegram 處理器
│   │   ├── commands.py     # 指令處理
│   │   ├── callbacks.py    # 回調處理
│   │   └── messages.py     # 訊息處理
│   └── claude/             # Claude 整合
│       └── session.py      # Session 管理
├── pyproject.toml
├── .env.example
└── README.md
```

## 相關專案

- [claude-code-acp](https://github.com/yazelin/claude-code-acp-py) - Python ACP for Claude
- [telegram-copilot-bot](https://github.com/willh/telegram-copilot-bot) - 原始 TypeScript 版本 (Copilot)

## 授權

MIT
