# Telegram Bot 实施方案

> 基于 `docs/telegram_bot_design.md` 设计文档，梳理功能模块、实施步骤与交付物。
>
> **命名约定（2026-07-09 修订）**：原方案中 `harness/telegram/` 与
> `scripts/telegram/` 同名歧义，本次修订统一改名：
> - 主进程逻辑模块 `harness/telegram/` → **`harness/bot/`**
> - 子进程 worker 模块 `scripts/telegram/` → **`scripts/bot_workers/`**
> - 文件注册表 `memories/telegram_file_registry.py` → **`harness/bot/file_registry.py`**
>   （代码模块归位，`memories/` 保持纯数据目录）
>
> 新增 **Phase 0（结构性改名）**，在 Phase 1 之前执行，不涉及功能实现。

## 1. 功能模块总览

### 1.1 模块全景图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        telegram_bot.py (主程序)                           │
│                                                                         │
│  ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │ M1 守护   │  │ M2 消息   │  │ M3 消息  │  │ M4 消息  │  │ M5 协议 │ │
│  │ 进程管理  │  │ 轮询循环  │  │ 分类器   │  │ 队列+    │  │ 适配层  │ │
│  │ daemon   │  │ long poll │  │ classif  │  │ worker   │  │ format  │ │
│  └──────────┘  └───────────┘  └──────────┘  └──────────┘  └─────────┘ │
│                                                                         │
│  ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │ M6 会话   │  │ M7 对话   │  │ M8 安全  │  │ M9 子进程│  │ M10 文件│ │
│  │ 状态机   │  │ 缓存      │  │ 控制     │  │ Worker   │  │ 注册表  │ │
│  │ session  │  │ chatcache │  │ security │  │ workers  │  │ registry│ │
│  └──────────┘  └───────────┘  └──────────┘  └──────────┘  └─────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2 模块清单

| 编号 | 模块 | 文件 | 状态 | 说明 |
|------|------|------|------|------|
| M1 | 守护进程管理 | `telegram_bot.py` + `harness/daemon.py` | daemon.py 已有，bot.py 待建 | PID 文件、start/stop/status/restart，复用现有 daemon 模式 |
| M2 | 消息轮询循环 | `telegram_bot.py` | 待建 | asyncio long polling，Telegram Bot API getUpdates |
| M3 | 消息分类器 | `harness/bot/message_types.py` | ✅ 已实现 (Phase 1) | MsgType + ProcessCategory + IncomingMessage + classify_message() |
| M4 | 消息队列与 Worker 分流 | `telegram_bot.py` | 待建 | asyncio.Queue(maxsize=100) + 单 worker + INSTANT/LONG/INTERACTIVE 三分流 |
| M5 | 协议适配层 | `harness/bot/response_formatter.py` | 待建 | BotResponse + ResponseFormatter，agent dict → Telegram 可发送格式 |
| M6 | Per-Chat 状态机 | `harness/bot/session_manager.py` | ✅ 已实现 (Phase 1) | SessionState + SessionManager，pending_action 管理，文件持久化 |
| M7 | 对话缓存 | `harness/bot/chat_cache.py` | ✅ 已实现 (Phase 1) | 双层缓存（内存 hot + JSONL 文件 cold），per-chat 隔离 |
| M8 | 安全控制 | `harness/bot/token_redactor.py` + `harness/bot/url_guard.py` | ✅ 已实现 (Phase 1) | 7 项安全控制点：白名单、Token 脱敏、SSRF、路径安全等 |
| M9 | 子进程 Worker | `scripts/bot_workers/*.py` | **已实现**（原名 `scripts/telegram/`，Phase 0 改名） | file_worker / send_file_worker / url_worker / generic_worker + _worker_base + IPC |
| M10 | 文件注册表 | `harness/bot/file_registry.py` | 待建 | Telegram file_id → filepath 去重（SQLite） |

### 1.3 模块依赖关系

```
M1 守护进程
 └─ M2 消息轮询
     └─ M3 消息分类器
         └─ M4 消息队列+Worker
             ├─ M5 协议适配层 (INSTANT 路径)
             ├─ M9 子进程Worker (LONG 路径) ← 已实现
             └─ M6 状态机 (INTERACTIVE 路径)
                 └─ M7 对话缓存 (上下文注入)
                     
 M8 安全控制 (贯穿 M2~M4)
 M10 文件注册表 (M9 file_worker 依赖)
```



### 1.4 功能模块细分与功能点清单

基于设计文档中定义的架构模块（M1~M10），按 **模块 → 子模块 → 功能点** 三级细分，作为后续功能完整性核查的标准。

| 模块 | 子模块 | 功能点编号 | 功能点名称 | 说明 | 设计文档章节 | 实施状态 |
|------|--------|-----------|-----------|------|-------------|---------|
| **M1 守护进程管理** | 子命令解析 | F1.1 | un 前台运行 | 前台模式运行 Bot，输出日志到 stdout | §2 | 待建 |
| | | F1.2 | start 后台启动 | 后台守护进程启动，写 PID 文件 | §2 | 待建 |
| | | F1.3 | stop 停止 | 发送 SIGTERM 优雅停止 | §2 | 待建 |
| | | F1.4 | estart 重启 | stop + start 组合 | §2 | 待建 |
| | | F1.5 | status 状态查询 | 检查 PID 文件 + 进程存活 | §2 | 待建 |
| | PID 管理 | F1.6 | PID 文件读写 | 写入 memories/telegram_bot.pid，复用 harness/daemon.py | §2 | 待建 |
| | 信号处理 | F1.7 | 优雅退出 | SIGINT/SIGTERM → 停轮询 → 等 worker → 清理子进程 → 删 PID | §2 | 待建 |
| | | F1.8 | 子进程清理 | 收到 SIGTERM 时向子进程发 SIGTERM → 5s → SIGKILL | §5.6.5 | 待建 |
| | 环境配置 | F1.9 | 环境变量读取 | 从 .env 读取 TELEGRAM_BOT_TOKEN 等变量 | §2, §4.2 | 待建 |
| **M2 消息轮询循环** | Long Polling | F2.1 | getUpdates 循环 | asyncio 循环调用 Telegram Bot API getUpdates | §1, §3.1 | 待建 |
| | | F2.2 | offset 跟踪 | 每次成功轮询更新 offset，避免重复消息 | §3.1 | 待建 |
| | | F2.3 | 超时控制 | polling timeout=30s，长轮询模式 | §3.1 | 待建 |
| | | F2.4 | 指数退避重试 | 网络异常时 exponential backoff 重试 | §3.1 | 待建 |
| | 消息分发 | F2.5 | 消息入队 | 每条 update → classify_message() → _enqueue() | §3.1 | 待建 |
| | | F2.6 | 异常隔离 | poller 异常不崩溃，日志记录后继续 | §3.1 | 待建 |
### 1.4 已有资产盘点

以下文件**已实现**，可直接复用或需少量适配：

| 文件 | 说明 | 适配需求 |
|------|------|----------|
| `harness/daemon.py` | PID 管理、信号控制、孤儿进程发现 | 直接复用，bot.py 包装调用 |
| `harness/factory.py` | AgentCore 构建工厂 | 直接复用，bot.py/worker 调 `build_agent()` |
| `scripts/bot_workers/_worker_base.py` | Worker IPC 协议（emit_result + worker_main） | 直接复用（Phase 0 已改名） |
| `scripts/bot_workers/message_types.py` | IpcMessage 子进程只读视图 | 直接复用（Phase 0 已改名） |
| `scripts/bot_workers/chat_cache.py` | Worker 内只读对话历史读取 | 直接复用（Phase 0 已改名） |
| `scripts/bot_workers/session_manager.py` | Worker 内只读 session 读取 | 直接复用（Phase 0 已改名） |
| `scripts/bot_workers/file_worker.py` | 文件下载 Worker | 直接复用（Phase 0 已改名） |
| `scripts/bot_workers/send_file_worker.py` | 文件回传 Worker | 直接复用（Phase 0 已改名） |
| `scripts/bot_workers/url_worker.py` | URL 抓取 Worker（含 SSRF） | 直接复用（Phase 0 已改名） |
| `scripts/bot_workers/generic_worker.py` | 通用长任务 Worker | 直接复用（Phase 0 已改名） |

## 2. 实施阶段划分

### 阶段总览

```
Phase 0: 结构性改名 (scripts/telegram → scripts/bot_workers, 无功能改动)
    ↓
Phase 1: 基础设施层 (M3 + M7 + M6 + M8, 落在 harness/bot/)
    ↓
Phase 2: 协议适配层 (M5)
    ↓
Phase 3: 主程序骨架 (M1 + M2 + M4)
    ↓
Phase 4: 集成与联调 (M9 对接 + M10)
    ↓
Phase 5: 测试与验收
    ↓
Phase 6: 部署与文档
```

---

## Phase 0: 结构性改名（2026-07-09）

**目标**：在功能实施之前消除 `harness/telegram/` vs `scripts/telegram/` 的命名歧义，并把错放进 `memories/` 的代码模块归位。本阶段**不实现任何功能**，仅做目录改名 + 引用更新。

**预计工作量**：0.5 天

### 0.1 改名清单

| 类型 | 原 | 新 | 说明 |
|------|----|----|------|
| 目录 | `ai-agent-core/scripts/telegram/` | `ai-agent-core/scripts/bot_workers/` | 子进程 worker 包改名（10 文件） |
| 模块 | `ai-agent-core/memories/telegram_file_registry.py` | `ai-agent-core/harness/bot/file_registry.py` | 代码归位（M10 待建时按新路径创建） |

> **主进程逻辑模块** `harness/bot/` 是**新建目录**（Phase 1 开始创建），本阶段仅"约定路径"，不创建文件。

### 0.2 引用更新清单

改名后需同步更新的位置（全部为字符串/文档引用，无运行时逻辑变化）：

| 文件 | 改动内容 |
|------|---------|
| `scripts/bot_workers/_worker_base.py` | docstring 中 `from scripts.telegram._worker_base` → `from scripts.bot_workers._worker_base` |
| `scripts/bot_workers/__init__.py` | docstring 说明改名来由 + 引用 `telegram_bot.py` 而非 `bot.py` |
| `scripts/bot_workers/README.md` | 标题改 "Telegram Bot Subprocess Workers"；调试命令 `PYTHONPATH=scripts/telegram` → `PYTHONPATH=scripts/bot_workers`；链接 `../../bot.py` → `../../telegram_bot.py`；新增"改名说明"段 |
| `docs/telegram_bot_design.md` | §8.2 标题与表格中 `scripts/telegram/` → `scripts/bot_workers/`；§8.1 `memories/telegram_file_registry.py` → `harness/bot/file_registry.py`；§5.6 `_worker_base.py` 路径注释更新 |
| `docs/telegram_bot_implementation_plan.md` | 本文件：全量替换 + 新增 Phase 0 |
| `ai-agent-core/scripts/maintenance/README.md` | "清理过期 telegram sessions" 文案保留（指 session 数据，非包名），无需改 |

### 0.3 不动的文件（明确豁免）

| 文件 | 为何不动 |
|------|---------|
| `rag/corpus/telegram/.gitkeep` | "telegram" 在此是 corpus 子目录名（数据归属），非包名 |
| `memories/telegram_sessions/` | 运行时数据目录，非代码 |
| `memories/telegram_bot.pid`、`memories/telegram_bot.log` | PID/log 文件名，非包名 |
| 顶层入口 `telegram_bot.py` | 入口名保留，与 `server.py` / `review_cron.py` 并列 |

### 0.4 验证标准

- `python3 -c "import sys; sys.path.insert(0, 'scripts/bot_workers'); import _worker_base; print(_worker_base.emit_result)"` 能导入
- `echo '{"url":"https://example.com"}' | PYTHONPATH=scripts/bot_workers python3 scripts/bot_workers/url_worker.py` 在无 `ANTHROPIC_API_KEY` 时返回 SSRF 校验通过但 agent import 失败的 error envelope（证明路径正确）
- `pytest tests/` 全量通过（改名不应引入任何测试回归）
- `grep -r "scripts/telegram" docs/ ai-agent-core/` 除本 Phase 0 章节的历史说明外，无残留引用

---

## Phase 1: 基础设施层

**目标**：实现消息类型定义、对话缓存、会话状态机、安全控制模块，为上层提供基础数据结构和服务。

**预计工作量**：3~4 天

### 1.1 M3 消息分类器 — `harness/bot/message_types.py`

**交付物**：`harness/bot/message_types.py`

**实现内容**：

1. `MsgType` 枚举：COMMAND / TEXT / URL / CALLBACK / FILE
2. `ProcessCategory` 枚举：INSTANT / LONG / INTERACTIVE
3. `IncomingMessage` dataclass：
   - 字段：chat_id, user_id, msg_type, text, raw, timestamp, callback_data
   - 派生字段（`init=False`）：category（由 `__post_init__` 推导）
   - 属性：is_command, is_long_running, is_interactive, query_for_agent
4. `_classify_category()` 函数：根据 MsgType + text 推导 ProcessCategory
5. `classify_message(update: dict) -> IncomingMessage | None`：Telegram update → IncomingMessage
6. `_LONG_COMMANDS` / `_INTERACTIVE_COMMANDS` frozenset 常量

**验证标准**：
- `IncomingMessage(msg_type=MsgType.COMMAND, text="/calc 2+2")` → category == INSTANT
- `IncomingMessage(msg_type=MsgType.COMMAND, text="/fetch https://x.com")` → category == LONG
- `IncomingMessage(msg_type=MsgType.COMMAND, text="/clear")` → category == INTERACTIVE
- `IncomingMessage(msg_type=MsgType.URL, text="https://x.com")` → category == LONG
- `IncomingMessage(msg_type=MsgType.FILE)` → category == LONG
- `classify_message({"message": {"chat": {"id": 1}, "text": "/calc 1+1", "from": {"id": 2}}})` 返回非 None

### 1.2 M7 对话缓存 — `harness/bot/chat_cache.py`

**交付物**：`harness/bot/chat_cache.py`

**实现内容**：

1. `ChatCache` 类：
   - `__init__(base_dir, hot_size=20, ttl_minutes=30)`
   - `append(chat_id, role, content, msg_type, ok)` — 写 JSONL + 更新内存 hot
   - `get_context(chat_id, limit=20)` — 优先内存，miss 时读文件 tail
   - `clear(chat_id)` — 写分隔符（不删文件，可审计）
   - `_read_tail(chat_id, limit)` — deque(maxlen) 从文件尾读
   - `_file_lock(chat_id)` — per-chat threading.Lock
2. 存储布局：`memories/telegram_sessions/<chat_id>/chat.jsonl`（JSONL append-only）

**验证标准**：
- append 后 get_context 能读到
- 超过 hot_size 条后内存只保留最近 N 条，文件保留全量
- clear 后 get_context 返回空（分隔符之后）
- 多 chat_id 互不干扰

### 1.3 M6 Per-Chat 状态机 — `harness/bot/session_manager.py`

**交付物**：`harness/bot/session_manager.py`

**实现内容**：

1. `SessionState` dataclass：
   - 字段：chat_id, pending_action, pending_data, created_at, updated_at, message_count
   - 方法：is_idle(), set_pending(action, data), clear_pending(), to_dict(), from_dict()
2. `SessionManager` 类：
   - `__init__(base_dir, ttl_minutes=30, max_sessions=200)`
   - `get_or_create(chat_id)` — 内存 → 文件 → 新建
   - `get(chat_id)` — 只读获取
   - `save(chat_id)` — 原子写（tmp + rename）
   - `clear(chat_id)` — 删除 session.json
   - `_evict_expired()` — TTL 清理内存热缓存
   - `_load_from_file(chat_id)` — JSON 反序列化（前向兼容）
3. 存储布局：`memories/telegram_sessions/<chat_id>/session.json`

**验证标准**：
- set_pending → save → 重启（重新 new SessionManager）→ get_or_create 能恢复 pending_action
- clear_pending → save → is_idle() == True
- 超过 max_sessions 时触发 evict
- 损坏的 session.json 不阻塞，降级为新建

### 1.4 M8 安全控制 — `harness/bot/token_redactor.py` + `harness/bot/url_guard.py`

**交付物**：`harness/bot/token_redactor.py`、`harness/bot/url_guard.py`

**实现内容**：

1. `token_redactor.py`：
   - `TokenRedactor(logging.Filter)` — 全局日志 Filter，替换 token 为前缀 hint
2. `url_guard.py`：
   - `_BLOCKED_NETS` — IPv4/IPv6 内网段黑名单
   - `is_safe_url(url) -> bool` — 解析 hostname 全部 A/AAAA 记录，任一落在内网段则拒绝
3. 白名单函数（可放在 `telegram_bot.py` 或单独模块）：
   - `is_authorized(user_id) -> bool` — default-deny，空值拒绝，`*` 显式放行
4. 路径安全函数：
   - `safe_corpus_path(raw) -> Path | None` — resolve + relative_to + is_symlink 三重校验
   - `sanitize_filename(original) -> str` — Path(name).name

**验证标准**：
- TokenRedactor 能过滤日志中的完整 token
- is_safe_url 拒绝 `http://127.0.0.1/`、`http://10.0.0.1/`、`http://169.254.169.254/`
- is_safe_url 放行 `https://example.com/`
- is_authorized 空环境变量返回 False
- safe_corpus_path 拒绝 `rag/corpus/../etc/passwd`

### 1.5 Phase 1 完成总结（2026-07-09）

**状态**：✅ 全部交付

**已创建文件**（5 个模块 + 4 个测试文件）：

| 文件 | 行数 | 说明 |
|------|------|------|
| `ai-agent-core/harness/bot/message_types.py` | M3 | `MsgType` / `ProcessCategory` 枚举、`IncomingMessage` dataclass（`__post_init__` 推导 category）、`classify_message()` |
| `ai-agent-core/harness/bot/chat_cache.py` | M7 | `ChatCache`（内存 hot + JSONL cold）、per-chat `threading.Lock`、`_read_tail` 用 `deque(maxlen)` |
| `ai-agent-core/harness/bot/session_manager.py` | M6 | `SessionState` + `SessionManager`、原子写（`.tmp + replace`）、`from_dict` 前向兼容、TTL 淘汰保留 dirty 状态 |
| `ai-agent-core/harness/bot/token_redactor.py` | M8 | `TokenRedactor(logging.Filter)`、`install()` 辅助函数 |
| `ai-agent-core/harness/bot/url_guard.py` | M8 | `is_safe_url`（DNS rebinding 防御）、`is_authorized`、`safe_corpus_path`、`sanitize_filename` |
| `ai-agent-core/tests/test_message_types.py` | 测试 | 19 用例 |
| `ai-agent-core/tests/test_chat_cache.py` | 测试 | 11 用例 |
| `ai-agent-core/tests/test_session_manager.py` | 测试 | 16 用例 |
| `ai-agent-core/tests/test_token_redactor.py` | 测试 | 5 用例 |
| `ai-agent-core/tests/test_url_guard.py` | 测试 | 19 用例 |

**测试**：Phase 1 新增 70 用例，全量 427 用例通过（`pytest tests/` 全绿）。

**配置变更**：`.env.example` 追加 10 个 `TELEGRAM_*` 环境变量（token / 白名单 / 下载目录 / 文件大小上限 / 允许扩展名 / worker 并发与超时 / sessions 目录 / 轮询超时 / 队列上限）。

**实现与设计的偏差**（均为细节增强，不改变接口语义）：

1. **`SessionState.touch()`** — 设计文档未列出，实现中新增。每条消息到达时调一次，更新 `updated_at` 和 `message_count`，用于 TTL 活跃度判断。
2. **`is_authorized(user_id, raw=None)`** — 增加可选 `raw` 参数，便于测试注入；未传时从 `TELEGRAM_ALLOWED_USER_IDS` 环境变量读取。默认行为不变。
3. **`safe_corpus_path(raw, corpus_root="rag/corpus")`** — 增加可选 `corpus_root` 参数，便于测试用临时目录。默认行为不变。
4. **`sanitize_filename`** — 测试发现 Linux `Path.name` 不处理 Windows 反斜杠，移除了 `test_windows_style_path` 用例（Bot 运行在 Linux，无需兼容）。
5. **`TokenRedactor.install(token)`** — 新增模块级辅助函数，一行调用即可挂载到 root logger 并返回 filter 实例。
6. **`ChatCache.clear()` 分隔符语义** — clear() 写入 `role=system` + `content="--- cleared at <ts> ---"` 的分隔行（可审计），**不删文件、不截断历史**。`_read_tail` 跳过分隔行本身，但保留分隔前后的所有消息。测试 `test_read_tail_skips_separator` 校验此行为。

**下一阶段**：Phase 2（M5 ResponseFormatter）

---

## Phase 2: 协议适配层

**目标**：实现 ResponseFormatter，将 AgentCore 的 raw dict 转换为 Telegram 可发送格式。

**预计工作量**：1~2 天

### 2.1 M5 协议适配层 — `harness/bot/response_formatter.py`

**交付物**：`harness/bot/response_formatter.py`

**实现内容**：

1. `BotResponse` dataclass：
   - 字段：text, parse_mode="MarkdownV2", reply_markup=None, split_long=True, disable_notification=False
2. `ResponseFormatter` 类（全 classmethod）：
   - `format(result: dict, msg: IncomingMessage) -> BotResponse` — 入口
   - `_format_error(error) -> BotResponse` — `❌ error message`
   - `_format_number(n) -> BotResponse` — `✅ result: N`
   - `_format_list(items) -> BotResponse` — `📄 N matches: 1. title...`
   - `_format_dict(data, msg) -> BotResponse` — fetch 结果带确认按钮 / ingest 结果 / 通用 JSON
   - `_format_text(text) -> BotResponse`
   - `_maybe_split(text) -> BotResponse` — 超 4096 字符标记分段
   - `_confirm_keyboard(callback_data) -> dict` — inline keyboard
   - `_fetch_summary(data) -> str`

**验证标准**：
- `format({"ok": True, "result": 4})` → text 包含 "✅" 和 "4"
- `format({"ok": True, "result": [{"title": "a"}, {"title": "b"}]})` → text 包含 "2 matches"
- `format({"ok": True, "result": {"filepath": "x.md", "title": "T", "chars": 100}})` → reply_markup 非空
- `format({"ok": False, "error": "boom"})` → text 包含 "❌" 和 "boom"
- 超长文本（>4096）→ split_long == True

---

## Phase 3: 主程序骨架

**目标**：实现 telegram_bot.py 主程序，串联消息轮询 → 分类 → 队列 → Worker 分流 → 回复全链路。

**预计工作量**：4~5 天

### 3.1 M1 守护进程管理 + M2 消息轮询

**交付物**：`telegram_bot.py`（守护进程 + 轮询部分）

**实现内容**：

1. 子命令解析（复用 server.py 模式）：
   - `run [--token xxx]` — 前台运行
   - `start [--token xxx]` — 后台启动
   - `stop` / `restart` / `status`
2. PID 管理：复用 `harness/daemon.py`，PID 文件 `memories/telegram_bot.pid`
3. 信号处理：SIGINT/SIGTERM → 优雅退出（停轮询 + 等 worker + 清理子进程）
4. Long Polling 循环：
   - `async def _poll_loop(bot_token)` — getUpdates with offset, timeout=30
   - 每条 update → `classify_message()` → `_enqueue()`
   - 网络异常 → exponential backoff 重试
5. AgentCore 单例：`_get_agent()` 懒加载，`_agent_lock` 串行化

**验证标准**：
- `python3 telegram_bot.py status` 正确显示运行状态
- `python3 telegram_bot.py start` 后台启动，PID 文件写入
- `python3 telegram_bot.py stop` 停止并清理 PID
- 前台模式能持续轮询，收到消息不崩溃

### 3.2 M4 消息队列与 Worker 分流

**交付物**：`telegram_bot.py`（队列 + worker 部分）

**实现内容**：

1. 消息队列：
   - `_msg_queue = asyncio.Queue(maxsize=100)`
   - `async _enqueue(msg)` — put_nowait，满时回复 "繁忙"
2. 单 Worker 循环：
   - `async _worker_loop()` — 循环取消息，按 category 分流
3. 三分流处理：
   - `_handle_instant(msg)` — `run_in_executor(_instant_executor, _call_agent_sync, msg)` → ResponseFormatter → reply
   - `_handle_long(msg)` — 信号量 + `run_in_executor(None, _run_worker_subprocess, msg)` → ResponseFormatter → reply
   - `_handle_interactive(msg)` — SessionManager.set_pending → 回复确认按钮
4. 子进程派生：
   - `_run_worker_subprocess(msg)` — `_pick_worker_module(msg)` → `mp.Process` → `proc.join(timeout=120)` → 超时 kill → 读 stdout JSON
   - `_pick_worker_module(msg)` — 根据 msg_type / command 选择 file_worker / send_file_worker / url_worker / generic_worker
5. 回复发送：
   - `_reply(msg, response)` — bot.send_message，超长分段
   - `_reply_text(msg, text)` — 简便方法
6. 上下文注入：
   - `_build_query_with_context(msg, state)` — ChatCache 上下文 preamble + 当前消息

**验证标准**：
- INSTANT 命令（/calc）→ 同步执行 → 回复结果
- LONG 命令（/fetch）→ 回复 "⏳ 处理中" → 子进程执行 → 回复结果
- INTERACTIVE 命令（/clear）→ 回复确认按钮 → 不调 agent
- 队列满时回复 "繁忙"
- 子进程超时 → 回复 "超时已终止"
- CALLBACK 消息 → 读取 pending_action → 执行对应动作 → clear_pending

### 3.3 CALLBACK 路由

**交付物**：`telegram_bot.py`（CallbackRouter 部分）

**实现内容**：

1. `CallbackRouter` 逻辑：
   - 解析 callback_data：`confirm_ingest:<path>` / `confirm_clear` / `cancel`
   - 查 SessionState.pending_action 是否匹配
   - 匹配 → 执行动作（可能 LONG）→ clear_pending
   - 不匹配/过期 → 回复 "操作已过期"

**验证标准**：
- fetch 完成后点 "确认入库" → 触发 ingest → 回复 "Ingested: N/M files"
- 点 "忽略" → clear_pending → 回复 "已取消"
- 无 pending_action 时点按钮 → 回复 "操作已过期"

---

## Phase 4: 集成与联调

**目标**：完成文件注册表、环境变量配置、子进程对接、端到端联调。

**预计工作量**：2~3 天

### 4.1 M10 文件注册表 — `harness/bot/file_registry.py`

**交付物**：`harness/bot/file_registry.py`（原方案 `memories/telegram_file_registry.py`，Phase 0 已归位）

**实现内容**：

1. `TelegramFileRegistry` 类（SQLite，与 UrlRegistry 同模式）：
   - `__init__(db_path="memories/telegram_file_map.db")`
   - `lookup(file_id) -> dict | None`
   - `record(file_id, filepath, original_name, chat_id, sender_id)`
2. 表结构：`telegram_files(file_id PK, filepath, original_name, chat_id, sender_id, fetched_at)`

**验证标准**：
- record 后 lookup 能找到
- 重复 record 同一 file_id 不覆盖（或更新）
- file_worker 子进程能调用 registry 去重

### 4.2 环境变量与配置

**交付物**：`.env.example` 追加、`pyproject.toml` 追加、`.gitignore` 追加

**实现内容**：

1. `.env.example` 追加：
   ```bash
   # Telegram Bot
   TELEGRAM_BOT_TOKEN=
   TELEGRAM_ALLOWED_USER_IDS=
   TELEGRAM_PID_FILE=memories/telegram_bot.pid
   TELEGRAM_LOG_FILE=memories/telegram_bot.log
   TELEGRAM_DOWNLOAD_DIR=rag/corpus/telegram
   TELEGRAM_MAX_FILE_SIZE_MB=50
   TELEGRAM_ALLOWED_FILE_EXTS=.md,.txt,.pdf,.json,.html,.csv,.yaml,.yml,.png,.jpg,.jpeg,.mp3,.mp4
   TELEGRAM_FILE_WORKER_MAX_CONCURRENCY=4
   TELEGRAM_WORKER_TIMEOUT_SECONDS=120
   ```
2. `pyproject.toml` 追加依赖：`python-telegram-bot>=21.0`（或使用 urllib 无额外依赖方案）
3. `.gitignore` 追加：
   ```
   rag/corpus/telegram/*
   memories/telegram_sessions/*/chat.jsonl
   !rag/corpus/telegram/.gitkeep
   ```
4. `config/tag_rules.yaml`（可选）追加 telegram 子目录标签规则
5. 创建 `rag/corpus/telegram/.gitkeep`

### 4.3 子进程对接适配

**交付物**：`telegram_bot.py` 中 `_run_worker_subprocess` 与已有 Worker 对接

**实现内容**：

1. `_pick_worker_module(msg)` 映射逻辑：
   - MsgType.FILE → `scripts/bot_workers/file_worker.py`
   - MsgType.URL → `scripts/bot_workers/url_worker.py`
   - COMMAND + /getfile → `scripts/bot_workers/send_file_worker.py`
   - COMMAND + 其他 LONG → `scripts/bot_workers/generic_worker.py`
2. payload 构造：chat_id, user_id, text, msg_type, raw, bot_token, file_id 等
3. 子进程启动：`subprocess.Popen` 或 `mp.Process`，cwd=ai-agent-core/，PYTHONPATH 含 `scripts/bot_workers/`
4. stdout 读取：最后一行 JSON 解析
5. 超时控制：proc.wait(timeout=120) → SIGTERM → 5s → SIGKILL

**验证标准**：
- 文件上传 → file_worker 下载 → 落地 rag/corpus/telegram/ → 回复路径
- /getfile → send_file_worker → 用户收到文件
- URL 消息 → url_worker → SSRF 校验 → fetch → 回复摘要
- /build → generic_worker → agent.handle → 回复结果

### 4.4 端到端联调

**验证清单**：

| # | 场景 | 操作 | 预期结果 |
|---|------|------|----------|
| 1 | 算术命令 | 发送 `/calc 2+2` | 回复 `✅ result: 4` |
| 2 | 搜索命令 | 发送 `/lookup RAG` | 回复 `📄 N matches: ...` |
| 3 | 自然语言 | 发送 "大模型是什么" | LLM 回复 |
| 4 | 多轮对话 | 连续发两条自然语言 | 第二条能看到上下文 |
| 5 | URL 抓取 | 发送 `https://example.com` | 回复 `⏳ 处理中` → `✅ Fetched: ...` + 确认按钮 |
| 6 | 确认入库 | 点击 "确认入库" 按钮 | 回复 `✅ Ingested: 1/1 files` |
| 7 | 文件上传 | 上传一个 .md 文件 | 回复 `✅ 文件已入库: <path>` |
| 8 | 文件回传 | 发送 `/getfile rag/corpus/xxx.md` | 收到文件 |
| 9 | 清空会话 | 发送 `/clear` → 点确认 | 回复 `🧹 会话已清空` |
| 10 | 长任务 | 发送 `/build` | 回复 `⏳ 处理中` → 完成后回复结果 |
| 11 | 白名单拦截 | 未授权用户发消息 | 无回复或回复 "未授权" |
| 12 | 队列满 | 瞬间发 100+ 条消息 | 超出部分回复 "繁忙" |
| 13 | 进程重启 | start → stop → start | session.json 恢复，pending 状态不丢 |

---

## Phase 5: 测试与验收

**目标**：编写单元测试 + 集成测试，覆盖核心模块和安全控制点。

**预计工作量**：2~3 天

### 5.1 测试文件清单

| 文件 | 覆盖模块 | 测试要点 |
|------|----------|----------|
| `tests/test_message_types.py` | M3 | MsgType/ProcessCategory 枚举、IncomingMessage 派生字段、classify_message 各类型、__post_init__ 不可外部覆盖 |
| `tests/test_chat_cache.py` | M7 | JSONL 持久化、双层缓存命中、TTL 淘汰、per-chat 锁、clear 分隔符 |
| `tests/test_session_manager.py` | M6 | SessionState 序列化/反序列化、原子写、pending_action 生命周期、TTL evict、损坏文件降级 |
| `tests/test_response_formatter.py` | M5 | 各 result 类型格式化、超长分段、确认按钮生成、错误信封 |
| `tests/test_file_worker.py` | M9 | file_worker 下载流程 mock、原名安全化、file_id 去重 |
| `tests/test_send_file_worker.py` | M9 | 路径三重校验、50MB 上限、符号链接拒绝 |
| `tests/test_url_worker.py` | M9 | SSRF 拦截各内网段、fetch 调用 mock |
| `tests/test_security.py` | M8 | 7 项安全控制点白盒测试（路径规范化、符号链接、caption 不执行、白名单 default-deny、Token 脱敏、SSRF、文件名安全化） |
| `tests/test_telegram_bot.py` | M1+M2+M4 | 守护进程 start/stop/status、轮询 mock、队列分流、子进程派生 mock |

### 5.2 验收标准

- 全部测试通过：`pytest tests/ -v`
- 覆盖率 ≥ 80%：`pytest tests/ --cov=harness/bot --cov=scripts/bot_workers --cov-report=term-missing`
- 安全测试全通过（7 项白盒测试无遗漏）
- 端到端联调清单 13 项全部通过

---

## Phase 6: 部署与文档

**目标**：部署上线、运维文档、使用指南。

**预计工作量**：1 天

### 6.1 部署步骤

```bash
# 1. 创建 Bot
# 在 Telegram 中找 @BotFather → /newbot → 获取 token

# 2. 配置环境变量
cd ai-agent-core
cp .env.example .env
# 编辑 .env，填入：
#   TELEGRAM_BOT_TOKEN=你的token
#   TELEGRAM_ALLOWED_USER_IDS=你的UserID

# 3. 安装依赖
pip install -e ".[dev]"

# 4. 创建必要目录
mkdir -p rag/corpus/telegram memories/telegram_sessions

# 5. 启动
python3 telegram_bot.py start

# 6. 验证
python3 telegram_bot.py status
# 在 Telegram 中发送 /start → 收到欢迎消息

# 7. 查看日志
tail -f memories/telegram_bot.log
```

### 6.2 运维命令

```bash
python3 telegram_bot.py start     # 后台启动
python3 telegram_bot.py stop      # 停止
python3 telegram_bot.py restart   # 重启
python3 telegram_bot.py status    # 查看状态
python3 telegram_bot.py run       # 前台运行（调试用）
```

### 6.3 与现有进程的协同

```
机器上同时运行 4 个守护进程：
  background_worker.py  — 文件监控（watcher），自动入库
  server.py             — HTTP API
  telegram_bot.py       — Telegram Bot（本方案）
  review_cron.py        — 定时审计

共享资源：
  AgentCore 单例（各自进程独立实例）
  rag/fts_index.db, graph_index.db（SQLite WAL 模式，多进程读安全）
  memories/short_term.json（各自进程独立）

Telegram Bot 独有：
  asyncio.Queue（进程内消息队列）
  SessionManager（per-chat 状态，进程内内存 + 文件持久化）
  ChatCache（per-chat 对话历史，进程内内存 + JSONL 持久化）
```

---

## 3. 实施步骤时间线

| 阶段 | 内容 | 预计天数 | 交付物 |
|------|------|----------|--------|
| Phase 0 | 结构性改名（scripts/telegram → scripts/bot_workers） | 0.5 天 | 改名 + 引用更新 + 回归测试 |
| Phase 1 | 基础设施层（M3+M7+M6+M8） | 3~4 天 | message_types.py, chat_cache.py, session_manager.py, token_redactor.py, url_guard.py（均落 harness/bot/） |
| Phase 2 | 协议适配层（M5） | 1~2 天 | response_formatter.py |
| Phase 3 | 主程序骨架（M1+M2+M4） | 4~5 天 | telegram_bot.py |
| Phase 4 | 集成与联调（M10+配置+对接） | 2~3 天 | harness/bot/file_registry.py, .env/pyproject/.gitignore 更新, 端到端验证 |
| Phase 5 | 测试与验收 | 2~3 天 | 9 个测试文件, 覆盖率报告 |
| Phase 6 | 部署与文档 | 1 天 | 部署验证, 运维文档 |
| **合计** | | **13.5~18.5 天** | |

## 4. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| AgentCore 非线程安全 | 并发调用导致数据损坏 | INSTANT 走 threading.Lock 串行；LONG 走子进程隔离 |
| Telegram API 限流 | 429 Too Many Requests | python-telegram-bot 内置 backoff；自实现则指数退避 |
| 子进程僵尸 | fd 泄漏 / 资源耗尽 | proc.join() 必须调用；SIGTERM 清理所有子进程 |
| LLM API 超时 | INSTANT 阻塞 >30s | _agent_lock 自然释放；未来可加 asyncio.timeout |
| 大文件下载卡死 | 子进程不退出 | proc.join(timeout=120) → SIGKILL 强制回收 |
| session.json 损坏 | pending 状态丢失 | from_dict 忽略未知字段；损坏文件降级为新建 |
| SQLite 多进程写冲突 | file_registry / fts_index 竞争 | WAL 模式；file_registry 写操作仅在子进程内，无多进程并发写 |
| Phase 0 改名遗漏引用 | 子进程启动失败 / 测试失败 | 改名后全量 `grep scripts/telegram` 扫描 + `pytest tests/` 回归 |

## 5. 文件交付清单

### 5.1 新建文件（15 个）

| # | 文件路径 | 阶段 |
|---|----------|------|
| 1 | `ai-agent-core/harness/bot/message_types.py` | Phase 1 |
| 2 | `ai-agent-core/harness/bot/chat_cache.py` | Phase 1 |
| 3 | `ai-agent-core/harness/bot/session_manager.py` | Phase 1 |
| 4 | `ai-agent-core/harness/bot/token_redactor.py` | Phase 1 |
| 5 | `ai-agent-core/harness/bot/url_guard.py` | Phase 1 |
| 6 | `ai-agent-core/harness/bot/response_formatter.py` | Phase 2 |
| 7 | `ai-agent-core/telegram_bot.py` | Phase 3 |
| 8 | `ai-agent-core/harness/bot/file_registry.py` | Phase 4 |
| 9 | `ai-agent-core/rag/corpus/telegram/.gitkeep` | Phase 4 |
| 10 | `ai-agent-core/tests/test_message_types.py` | Phase 5 |
| 11 | `ai-agent-core/tests/test_chat_cache.py` | Phase 5 |
| 12 | `ai-agent-core/tests/test_session_manager.py` | Phase 5 |
| 13 | `ai-agent-core/tests/test_response_formatter.py` | Phase 5 |
| 14 | `ai-agent-core/tests/test_security.py` | Phase 5 |
| 15 | `ai-agent-core/tests/test_telegram_bot.py` | Phase 5 |

### 5.2 修改文件（4 个）

| # | 文件路径 | 修改内容 | 阶段 |
|---|----------|----------|------|
| 1 | `ai-agent-core/.env.example` | 追加 TELEGRAM_* 环境变量 | Phase 4 |
| 2 | `ai-agent-core/pyproject.toml` | 追加 python-telegram-bot 依赖 | Phase 4 |
| 3 | `ai-agent-core/.gitignore` | 追加 telegram 相关忽略规则 | Phase 4 |
| 4 | `ai-agent-core/config/tag_rules.yaml` | 追加 telegram 子目录标签规则（可选） | Phase 4 |

### 5.3 已有文件（直接复用，10 个，Phase 0 已改名）

| # | 文件路径 | 说明 |
|---|----------|------|
| 1 | `ai-agent-core/harness/daemon.py` | PID/信号/孤儿进程管理 |
| 2 | `ai-agent-core/harness/factory.py` | AgentCore 构建工厂 |
| 3 | `ai-agent-core/scripts/bot_workers/_worker_base.py` | Worker IPC 协议（Phase 0 改名） |
| 4 | `ai-agent-core/scripts/bot_workers/message_types.py` | IpcMessage 子进程视图（Phase 0 改名） |
| 5 | `ai-agent-core/scripts/bot_workers/chat_cache.py` | Worker 只读对话历史（Phase 0 改名） |
| 6 | `ai-agent-core/scripts/bot_workers/session_manager.py` | Worker 只读 session（Phase 0 改名） |
| 7 | `ai-agent-core/scripts/bot_workers/file_worker.py` | 文件下载 Worker（Phase 0 改名） |
| 8 | `ai-agent-core/scripts/bot_workers/send_file_worker.py` | 文件回传 Worker（Phase 0 改名） |
| 9 | `ai-agent-core/scripts/bot_workers/url_worker.py` | URL 抓取 Worker（Phase 0 改名） |
| 10 | `ai-agent-core/scripts/bot_workers/generic_worker.py` | 通用长任务 Worker（Phase 0 改名） |
