# Telegram Bot Claude ACP - 改寫計畫

## 原始專案分析

### 來源專案
- 路徑: `/home/ct/copilot/telegram-copilot-bot-v0.1.0`
- 語言: TypeScript (Node.js)
- 用途: 透過 Telegram 操作 GitHub Copilot CLI

### 原始依賴
| 套件 | 用途 |
|------|------|
| `@github/copilot-sdk` | Copilot CLI 的 SDK 封裝 |
| `node-telegram-bot-api` | Telegram Bot API |
| `dotenv` | 環境變數載入 |
| `glob` | 目錄 glob 匹配 |

### 核心功能

#### 1. Telegram 指令
| 指令 | 功能 |
|------|------|
| `/start`, `/help` | 顯示歡迎訊息 |
| `/dirs` | 列出工作目錄 (Inline Keyboard) |
| `/model [n]` | 切換 AI 模型 |
| `/status`, `/st` | 顯示 session 狀態 |
| `/reset` | 重啟 session |
| `/shutdown` | 關閉 bot |

#### 2. Copilot 整合
- Session 生命週期管理 (create/destroy/reset)
- 事件處理:
  - `assistant.message` - 最終回應
  - `assistant.message_delta` - 串流片段
  - `tool.execution_start` - 工具開始
  - `tool.execution_complete` - 工具完成
  - `session.idle` - 閒置狀態
- 佇列系統處理忙碌時的新請求

#### 3. 狀態管理 (ChatState)
```typescript
interface ChatState {
  client: CopilotClient | null;
  session: CopilotSession | null;
  dir?: string;
  model: string;
  busy: boolean;
  queue: string[];
  resetting: boolean;
  images?: string[];
  emoji?: string;
  currentPrompt?: string;
  toolStartMessages?: Map<string, ToolStartMessage>;
  // ... 其他欄位
}
```

#### 4. 特色功能
- 長訊息分割 (4096 字元限制)
- MarkdownV2 格式轉換
- 圖片附件處理
- 工具執行結果的「顯示參數」「顯示結果」按鈕
- Owner 權限檢查
- Session emoji 標記

---

## Python 改寫計畫

### 技術選型

| 原始 | Python 替代 | 說明 |
|------|-------------|------|
| `@github/copilot-sdk` | `claude-code-acp` | 我們的套件，使用 Claude CLI |
| `node-telegram-bot-api` | `python-telegram-bot` | 官方推薦，async 支援完整 |
| TypeScript | Python 3.10+ | 使用 dataclass, async/await |
| npm | uv | 現代 Python 套件管理 |

### 專案結構

```
telegram-bot-claude-acp/
├── pyproject.toml              # uv 專案配置
├── src/
│   └── telegram_claude_bot/
│       ├── __init__.py         # 版本與匯出
│       ├── __main__.py         # Entry point
│       ├── bot.py              # 主要 bot 邏輯
│       ├── handlers/
│       │   ├── __init__.py
│       │   ├── commands.py     # 指令處理 (/start, /dirs, etc.)
│       │   ├── callbacks.py    # Inline keyboard 回調
│       │   └── messages.py     # 訊息處理
│       ├── claude/
│       │   ├── __init__.py
│       │   ├── session.py      # Claude session 管理
│       │   └── events.py       # 事件處理
│       ├── state.py            # ChatState dataclass
│       ├── utils.py            # 工具函式
│       └── config.py           # 設定檔
├── .env.example
├── README.md
└── Dockerfile
```

### 依賴配置 (pyproject.toml)

```toml
[project]
name = "telegram-claude-bot"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "claude-code-acp>=0.3.4",
    "python-telegram-bot>=21.0",
    "python-dotenv>=1.0.0",
]
```

### 核心類別對照

#### ChatState (Python dataclass)
```python
@dataclass
class ChatState:
    client: ClaudeClient | None = None
    session_id: str | None = None
    cwd: str | None = None
    model: str = "claude-sonnet-4"
    busy: bool = False
    queue: list[str] = field(default_factory=list)
    resetting: bool = False
    images: list[str] = field(default_factory=list)
    emoji: str = ""
    current_prompt: str | None = None
    tool_results: dict[str, ToolResult] = field(default_factory=dict)
```

### 事件對照

| Copilot SDK 事件 | claude-code-acp 對應 |
|------------------|---------------------|
| `assistant.message` | `@client.on_complete` + response |
| `assistant.message_delta` | `@client.on_text` |
| `tool.execution_start` | `@client.on_tool_start` |
| `tool.execution_complete` | `@client.on_tool_end` |
| `session.idle` | query() 完成後自動 |

### 主要差異

1. **Session 管理**
   - 原始: `CopilotClient.createSession()` 回傳 session 物件
   - 改寫: `ClaudeClient.start_session()` + `query()` 方式

2. **事件處理**
   - 原始: `session.on(callback)` 註冊回調
   - 改寫: 裝飾器 `@client.on_text`, `@client.on_tool_start` 等

3. **權限控制**
   - 原始: Copilot SDK 自動處理
   - 改寫: `@client.on_permission` 處理器

4. **模型切換**
   - 原始: 在 createSession 時指定
   - 改寫: Claude CLI 不支援動態切換，需重啟

---

## 實作步驟

### Phase 1: 基礎架構
1. [ ] 建立專案目錄與 pyproject.toml
2. [ ] 實作 config.py (環境變數載入)
3. [ ] 實作 state.py (ChatState dataclass)
4. [ ] 實作 utils.py (目錄展開、訊息分割等)

### Phase 2: Telegram Bot
5. [ ] 實作 bot.py (Application 初始化)
6. [ ] 實作 handlers/commands.py (/start, /dirs, /status, /reset)
7. [ ] 實作 handlers/callbacks.py (Inline keyboard 處理)
8. [ ] 實作 handlers/messages.py (一般訊息處理)

### Phase 3: Claude 整合
9. [ ] 實作 claude/session.py (ClaudeClient 封裝)
10. [ ] 實作 claude/events.py (事件處理器)
11. [ ] 整合到 handlers 中

### Phase 4: 完善功能
12. [ ] 圖片附件處理
13. [ ] 長訊息分割
14. [ ] MarkdownV2 格式轉換
15. [ ] 工具結果按鈕

### Phase 5: 測試與文件
16. [ ] 測試各項功能
17. [ ] 撰寫 README.md
18. [ ] 建立 Dockerfile

---

## 環境變數

```env
# Required
TELEGRAM_BOT_TOKEN=your_telegram_bot_token

# Optional
DIRECTORY_PATTERNS=/path/to/projects/*,/path/to/libs/**
OWNER_CHAT_ID=123456789
DEFAULT_MODEL=claude-sonnet-4
```

---

## 備註

### 原始專案特色保留
- ✅ 目錄選擇 (Inline Keyboard)
- ✅ 模型切換
- ✅ 佇列系統
- ✅ Session emoji
- ✅ 工具執行追蹤
- ✅ Owner 權限檢查

### 改進項目
- 使用 Claude CLI 替代 Copilot CLI
- 更好的 async/await 支援
- 更清晰的模組化結構
- 使用 uv 管理依賴
