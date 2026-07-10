# Telegram 机器人双工通信方案设计

## 1. 架构总览

```
┌──────────────────────────────────────────────────────────────────────┐
│                    telegram_bot.py (常驻守护进程)                       │
│                                                                      │
│  ┌─────────────┐     ┌─────────────────────────────────────────┐     │
│  │  Long Poll  │────▶│       Message Classifier                  │     │
│  │  Loop       │     │       (MsgType 判定 → IncomingMessage)    │     │
│  │  (asyncio)  │     │                                          │     │
│  └─────────────┘     │  text.startswith("/")                   │     │
│                      │    → MsgType.COMMAND                     │     │
│                      │  text matches URL regex                  │     │
│                      │    → MsgType.URL                         │     │
│                      │  msg.document/photo/audio/video          │     │
│                      │    → MsgType.FILE                        │     │
│                      │  callback_query                          │     │
│                      │    → MsgType.CALLBACK                    │     │
│                      │  else                                    │     │
│                      │    → MsgType.TEXT (自然语言)              │     │
│                      └──────────┬───────────────────────────────┘     │
│                                 │                                     │
│                                 ▼                                     │
│                      ┌──────────────────────┐                        │
│                      │  asyncio.Queue       │  ← FIFO 缓冲            │
│                      │  (maxsize=100)       │  ← poller 不阻塞        │
│                      └──────────┬───────────┘                        │
│                                 │                                     │
│                                 ▼                                     │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │  Single Worker (asyncio.Task)                                │    │
│  │                                                              │    │
│  │  1. 取 IncomingMessage                                        │    │
│  │  2. 查 SessionState (per chat_id)                             │    │
│  │  3. 构造 query (含上下文 preamble)                             │    │
│  │  4. agent.handle(query) → {"ok", "result", "error"}          │    │
│  │  5. ResponseFormatter → BotResponse                           │    │
│  │  6. bot.send_message()                                        │    │
│  │                                                              │    │
│  │  长任务分流:                                                   │    │
│  │    build similarity / ingest / review                         │    │
│  │      → ThreadPoolExecutor → 完成后回调回复                      │    │
│  └──────────────────────────────────────────────────────────────┘    │
│         │           │              │                                  │
│         ▼           ▼              ▼                                  │
│  ┌────────────┐ ┌─────────────┐ ┌──────────────────┐                │
│  │CommandMapper│ │ FileHandler │ │  SessionManager   │                │
│  │             │ │             │ │  (per chat_id)    │                │
│  │ /calc 2+2   │ │ 接收:       │ │                   │                │
│  │ → "calc 2+2"│ │ TG→corpus   │ │  SessionState:    │                │
│  │ /fetch URL  │ │ 发送:       │ │   chat_id         │                │
│  │ → fetch URL │ │ /getfile    │ │   pending_action  │                │
│  │ /getfile p  │ │             │ │   pending_data    │                │
│  │ → 文件回传  │ │             │ │   history: [...]  │                │
│  └────────────┘ └─────────────┘ │   updated_at      │                │
│                                  └──────────────────┘                │
│                                                                      │
│  PID 管理: harness/daemon.py (与 server.py/watcher 同模式)            │
│  start / stop / status / restart                                    │
└──────────────────────────────────────────────────────────────────────┘
         ↕  HTTPS Long Polling
    Telegram Bot API
         ↕
    用户手机 (Telegram App)

  文件落地后由 background_worker.py (watcher) 自动接管:
    清洗 → 规则打标 → FTS5 → graph_index → knowledge_edges
```

## 2. 进程管理（复用现有 daemon 模式）

与 `server.py`、`background_worker.py` 完全一致的守护进程模式：

```
python3 telegram_bot.py run [--token xxx]      # 前台运行
python3 telegram_bot.py start [--token xxx]    # 后台启动
python3 telegram_bot.py stop                   # 停止
python3 telegram_bot.py restart                # 重启
python3 telegram_bot.py status                 # 查看状态
```

**新增环境变量**（追加到 `.env.example`）：

```bash
# Telegram Bot
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...           # @BotFather 获取
TELEGRAM_ALLOWED_USER_IDS=                     # 逗号分隔白名单（空=不限制）
TELEGRAM_PID_FILE=memories/telegram_bot.pid
TELEGRAM_LOG_FILE=memories/telegram_bot.log
# Telegram 文件收发
TELEGRAM_DOWNLOAD_DIR=rag/corpus/telegram      # 接收文件的落地目录（相对 pkg/ai-agent-core/）
TELEGRAM_MAX_FILE_SIZE_MB=50                   # 单文件大小上限（MB），超限拒绝
TELEGRAM_ALLOWED_FILE_EXTS=.md,.txt,.pdf,.json,.html,.csv,.yaml,.yml,.png,.jpg,.jpeg,.mp3,.mp4  # 允许接收的扩展名（空=全部）
```

## 3. 指令类：命令映射

Telegram 消息以 `/` 开头 → 剥离 `/` 前缀 → 直接作为 `agent.handle()` 的 query。

| Telegram 命令 | 映射为 agent query | 说明 |
|---|---|---|
| `/calc 2 + 2` | `calc 2 + 2` | 算术 |
| `/lookup python` | `lookup python` | FTS5 搜索 |
| `/search 大模型` | `搜索 大模型` | 中文搜索 |
| `/list` | `list` | 列出全部文档 |
| `/tags` | `tags` | 查看标签 |
| `/filter [精华] [科技]` | `filter [精华] [科技]` | 标签过滤 |
| `/fetch https://example.com` | `fetch https://example.com` | 抓取网页 |
| `/hybrid 个人主权` | `hybrid 个人主权` | 混合 RAG |
| `/chunks rag/corpus/foo.md` | `chunks rag/corpus/foo.md` | chunk 检索 |
| `/tree . -L 2` | `tree . -L 2` | 目录树 |
| `/find skills -name *.py` | `find skills -name *.py` | 文件查找 |
| `/grep -rn "import" tests/` | `grep -rn "import" tests/` | 内容搜索 |
| `/context` | `context` | 上下文恢复 |
| `/review 科技 AI` | `review 科技 AI` | 认知审计 |
| `/reflect path --insight ...` | `reflect path --insight ...` | 实践复盘 |
| `/react 先算10/2` | `react 先算10/2` | ReAct 多步 |
| `/getfile rag/corpus/foo.md` | — | 把项目内文件回传给用户 |
| `/help` | — | 显示命令列表 |
| `/start` | — | 欢迎消息 |
| `/clear` | — | 清空当前会话缓存 |

**映射逻辑极简**：`query = text[1:]`（去掉 `/`），直接喂 `agent.handle(query)`。routing.yaml 已有的 regex 自动路由到对应 skill/MCP。

`/getfile` 与 `/fetch` 方向相反：`/fetch` 从外网抓取内容入库；`/getfile` 从项目内部把已入库的文件发送回 Telegram 用户。两者都只处理文本/Markdown 路径，二进制文件（图片/音视频）走下文的 FileHandler。

## 3.5 文件收发：FileHandler + URLHandler

Telegram 机器人支持双向文件流：用户可直接在 Telegram 中发送文件 → 自动入库；用户发 URL → agent 抓取入库；用户用 `/getfile` 命令反向取回项目内文件。

### 3.5.1 文件接收（Telegram → 项目）

```
用户在 Telegram 中发送 document/photo/audio/video
        │
        ▼
┌─────────────────────────────────┐
│  MessageDispatcher              │
│  判定 message_type:             │
│    - document (file)            │
│    - photo (image)              │
│    - audio (mp3/ogg)            │
│    - video (mp4)                │
│    - voice (ogg opus)           │
└───────────┬─────────────────────┘
            │
            ▼
┌─────────────────────────────────┐
│  FileHandler.receive()          │
│                                 │
│  1. 白名单校验（user_id）        │
│  2. 扩展名白名单校验             │
│  3. 大小上限校验 (MB)            │
│  4. 立即回复 "⏳ 接收中..."       │
│  5. 派生子进程                   │
│     FileWorkerChild.process(    │
│       file_id, chat_id, ...)    │
│  6. 子进程内完成:                │
│     a. file_id → getFile API    │
│     b. HTTPS GET 下载二进制      │
│     c. 落地 rag/corpus/         │
│        telegram/                │
│        YYYYMMDD_HHMMSS_<原名>   │
│     d. 写 TelegramFileRegistry  │
│  7. 子进程退出码:                │
│     0=成功, 非0=失败             │
│  8. 主进程检测退出,回调回复用户   │
│     - 0: 文件已入库 + 路径        │
│     - 非0: ❌ 接收失败 + 错误     │
└─────────────────────────────────┘
```

**子进程模型的核心理由**：

| 关注点 | 线程/协程方案 | 子进程方案(本设计) |
|--------|--------------|-------------------|
| 内存隔离 | 文件二进制与主进程共享内存,大文件可能撑爆 | 子进程独立地址空间,退出即释放 |
| 崩溃隔离 | 下载库抛段错误会拖垮整个 Bot | 子进程崩溃不影响主进程轮询 |
| 超时控制 | 需手动 cancel + 清理资源 | `proc.wait(timeout=N)` + `proc.kill()` 强制回收 |
| 资源泄漏 | httpx 连接池/SSL context 可能泄漏 | OS 级回收所有 fd/内存/连接 |
| 并发隔离 | GIL 限制 CPU 密集(如校验 hash) | 真并行,可同时多文件下载 |

**子进程生命周期**：

```
主进程 (telegram_bot.py)
   │
   ├──fork──> FileWorkerChild (PID: X1)  ──下载文件A──> 退出(0) ──> 回调回复用户A
   │
   ├──fork──> FileWorkerChild (PID: X2)  ──下载文件B──> 退出(0) ──> 回调回复用户B
   │
   └── (主进程继续 long poll,不阻塞)
```

子进程是"即用即弃"(disposable worker)——完成下载立即退出,不做长驻。主进程通过 `multiprocessing.Process` + `Queue` 或 `subprocess.run` 监控退出码与结果。最大并发由 `TELEGRAM_FILE_WORKER_MAX_CONCURRENCY` 控制(默认 4),超过则排队。

**落地路径规则**：

```
pkg/ai-agent-core/rag/corpus/telegram/
├── 20260709_103015_report.md
├── 20260709_103120_notes.txt
├── 20260709_103500_photo.jpg         # 图片走 save_img 同款逻辑
├── 20260709_104200_meeting.mp3
└── 20260709_104500_video.mp4
```

- **时间戳前缀**：`YYYYMMDD_HHMMSS_`,与 `fetch_web_to_md` 早期约定一致,便于日期范围过滤
- **原名保留**：紧贴时间戳后,避免重名覆盖
- **原名安全化**：`Path(original_name).name` 取 bare name,拒绝 `../`、绝对路径等注入
- **子目录隔离**：`telegram/` 子目录防止与手工 corpus 文件混淆,便于按来源过滤
- **去重**：同一 file_id 重复上传不覆盖,返回 `source_type="cached"`(参考 `UrlRegistry` 模式,新增 `TelegramFileRegistry` 记录 file_id→filepath)

**文件落地后的自动入库**：

`background_worker.py` 的 watcher 已经监控 `rag/corpus/` 递归子目录，新文件落地后自动触发：
1. 文本清洗（去首尾空白、丢空行）
2. 规则打 L1/L2/L3 标签（`config/tag_rules.yaml`，默认 L1=未分类 → 可配置专用规则识别 telegram 上传文件）
3. 注入 frontmatter（含 `fetched_at`、`source: telegram`）
4. upsert FTS5 (`rag/fts_index.db`)
5. upsert `document_graph` (`rag/graph_index.db`)
6. 解析 `[[wikilinks]]` 写入 `knowledge_edges`

无需 Telegram Bot 主动调用 pipeline，watcher 异步接管。二进制文件（图片/音视频）会被 watcher 跳过文本索引（FTS5 不支持二进制），但仍可被 `/getfile` 取回。

### 3.5.2 URL 抓取（Telegram URL 消息 → 项目 corpus）

用户在 Telegram 中发送一条纯 URL 消息（无 `/` 前缀，正则匹配 `^https?://`）：

```
用户发送 "https://example.com/article"
        │
        ▼
┌─────────────────────────────────┐
│  MessageDispatcher              │
│  text matches r'^https?://\S+'  │
└───────────┬─────────────────────┘
            │
            ▼
┌─────────────────────────────────┐
│  URLHandler.handle(url)         │
│                                 │
│  1. 白名单校验                   │
│  2. 构造 agent query:            │
│     f"fetch {url}"               │
│  3. agent.handle(query)          │
│     → 路由到 fetch_web_to_md skill│
│     → 默认落地到 rag/corpus/      │
│        <title>.md                │
│  4. 回复用户: 抓取完成 + 文件路径 │
│     + chars/links_count 摘要     │
└─────────────────────────────────┘
```

**与 `/fetch` 命令的区别**：

| 入口 | 触发条件 | 用户操作 |
|---|---|---|
| `/fetch <url>` | 显式 `/` 命令 | 用户需记得命令语法 |
| URL 消息（无前缀） | MessageDispatcher 正则识别 | 用户直接粘贴 URL，零认知负担 |

两者底层复用同一个 `fetch_web_to_md` skill，区别仅在 dispatcher 的路由逻辑。URLHandler 让 Telegram 机器人像"剪藏机器人"——随手转发链接即可入库。

**URL 去重**：复用 `UrlRegistry`（P0-2 已实现）。同一 URL 二次发送直接返回缓存路径，不重复抓取。

### 3.5.3 文件回传（项目 → Telegram）

`/getfile <path>` 命令把项目内已入库的文件发回给 Telegram 用户。文件发送是网络密集型耗时操作(50MB 文件上传可能 30s+),走子进程,与接收同模型:

```
用户发送 "/getfile rag/corpus/telegram/20260709_103015_report.md"
        │
        ▼
┌─────────────────────────────────┐
│  CommandHandler.handle_getfile  │
│                                 │
│  1. 路径安全三重校验:            │
│     a. Path(path).resolve()     │
│        规范化,消除 .. 和 ./      │
│     b. 必须以 rag/corpus/ 开头   │
│     c. is_symlink() 拒绝        │
│  2. 文件存在性检查               │
│  3. 文件大小检查（≤50MB，TG 限） │
│  4. 立即回复 "⏳ 发送中..."       │
│  5. 派生子进程 SendFileChild:    │
│     - bot.send_document(        │
│         chat_id, document=...)  │
│  6. 子进程退出码:                │
│     0=发送成功, 非0=失败         │
│  7. 主进程检测退出,回调回复:     │
│     - 0: ✅ 已发送 <文件名>      │
│     - 非0: ❌ 发送失败 + 错误     │
└─────────────────────────────────┘
```

**安全限制**:

- **路径规范化优先**:`Path(path).resolve()` 先解析为绝对路径,再校验是否以 `rag/corpus/` 开头。仅检查字符串 `..` 子串会被 `rag/corpus/./../../etc/passwd` 绕过
- **限定根目录**:必须以 `rag/corpus/` 开头(相对 `pkg/ai-agent-core/`),防止访问项目根之外的敏感文件(如 `.env`、`memories/short_term.json`)
- **显式拒绝 symlink**:`Path.is_symlink()` 返回 True 直接拒绝,防止 `rag/corpus/telegram/` 下恶意符号链接指向 `/etc/passwd`
- **文件大小上限 50MB**:Telegram Bot API 的 `sendDocument` 限制
- **子进程发送**:上传期间主进程继续 long poll,其他用户消息不阻塞

### 3.5.4 落地目录与 corpus 索引

`rag/corpus/telegram/` 作为子目录被 `CorpusLoader` 递归扫描，自动进入知识库：

```
pkg/ai-agent-core/rag/corpus/
├── (手工 Markdown 笔记)
├── 20260707_xxx.md
├── ...
└── telegram/                     ← 新增子目录
    ├── 20260709_103015_report.md  ← 文件接收落地
    ├── 20260709_103500_photo.jpg
    └── 20260709_104200_meeting.mp3
```

`MetadataIndex` 会自动从 `telegram/` 子目录的文件名中提取日期（`YYYYMMDD_HHMMSS_` 前缀），可通过 `filter` 命令按日期范围筛选。建议在 `config/tag_rules.yaml` 增加一条规则，让 telegram 子目录文件自动打上 `[telegram]` 标签：

```yaml
- l1: Telegram
  l2: 收纳
  l3: 上传
  keywords: []           # 不靠关键词
  path_contains: telegram  # 新增字段：路径包含则命中
```

（如不扩展 `tag_rules.yaml`，可让 telegram 文件默认归到 `未分类/Misc/General`，用户后续通过 `/filter` 按日期或路径前缀筛选。）

### 3.5.5 TelegramFileRegistry（去重注册表）

新增模块 `harness/bot/file_registry.py`（Phase 0 已由 `memories/telegram_file_registry.py` 归位），与 `UrlRegistry` 同款模式：

```python
class TelegramFileRegistry:
    """Telegram file_id → local filepath 去重注册表。"""

    def __init__(self, db_path: str = "memories/telegram_file_map.db"):
        # SQLite 表: telegram_files(file_id PK, filepath, original_name, chat_id, sender_id, fetched_at)
        ...

    def lookup(self, file_id: str) -> dict | None: ...
    def record(self, file_id: str, filepath: str, original_name: str,
               chat_id: int, sender_id: int) -> None: ...
```

同一用户重复上传同一文件（Telegram file_id 全局唯一）→ 直接返回缓存路径，不重复下载。`force` 参数绕过（参考 `UrlRegistry`）。

## 4. 非指令类：自然语言 + 消息缓存

### 4.1 流程

```
用户发送自然语言消息
        │
        ▼
┌───────────────────┐
│  ChatCache 写入   │  按 chat_id 隔离
│  (user, message)  │  保留最近 N 条
└───────┬───────────┘
        │
        ▼
┌───────────────────┐
│  构造 LLM query   │  缓存上下文 + 当前消息
│  → agent.handle() │  routing.yaml 末尾 .* → LLM fallback
└───────┬───────────┘
        │
        ▼
┌───────────────────┐
│  ChatCache 写入   │  (assistant, response)
│  + 回复 Telegram  │
└───────────────────┘
```

### 4.2 ChatCache 设计

对话上下文必须**持久化到本地文件**,而不是仅存内存。原因:

1. **进程重启不丢失**:Bot 重启后用户继续对话,历史可恢复
2. **可审计**:文件可 grep/统计,排查问题有据可查
3. **跨进程可见**:虽然 telegram_bot.py 独占 chat 文件,但 server.py/CLI 可读历史(调试用)
4. **内存可控**:历史归档到文件,内存仅保留最近 N 条 hot cache

**存储布局**:

```
memories/telegram_sessions/
├── <chat_id_123456>/
│   ├── chat.jsonl          # 全量对话历史(append-only, 每行一条)
│   ├── session.json        # 当前会话状态(pending_action/updated_at)
│   └── summary.md          # (可选)LLM 生成的历史摘要
├── <chat_id_789012>/
│   ├── chat.jsonl
│   └── session.json
└── index.json              # chat_id → last_active 映射(供 TTL 清理)
```

**新建对话 = 新建 chat_id 目录 + 创建文件**:

- 用户首次发消息 → `memories/telegram_sessions/<chat_id>/` 目录不存在 → 创建目录 + 初始化 `chat.jsonl`(空文件) + `session.json`(`{chat_id, created_at, pending_action: null}`)
- 后续消息 append 到 `chat.jsonl`,in-place 更新 `session.json`
- `/clear` 命令不删文件,而是 `chat.jsonl` 写入分隔符 `--- cleared at <ts> ---`,保留历史可审计

**文件格式**:

`chat.jsonl` (每行一条消息,JSON Lines):

```jsonl
{"ts": 1720523456.789, "role": "user", "content": "/calc 2+2", "msg_type": "COMMAND"}
{"ts": 1720523457.123, "role": "assistant", "content": "✅ result: 4", "ok": true}
{"ts": 1720523500.000, "role": "user", "content": "今天天气怎么样", "msg_type": "TEXT"}
{"ts": 1720523520.456, "role": "assistant", "content": "我无法查询实时天气...", "ok": true}
```

`session.json`:

```json
{
  "chat_id": 123456,
  "created_at": 1720523456.789,
  "updated_at": 1720523520.456,
  "pending_action": null,
  "pending_data": null,
  "message_count": 4
}
```

**ChatCache 类(双层缓存)**:

```python
class ChatCache:
    """Per-chat 对话缓存:内存 hot + 文件 cold(append-only)。"""

    def __init__(self, base_dir: str = "memories/telegram_sessions",
                 hot_size: int = 20, ttl_minutes: int = 30):
        self._base = Path(base_dir)
        self._hot: dict[int, list[dict]] = {}      # chat_id → 最近 N 条(内存)
        self._hot_size = hot_size
        self._ttl = ttl_minutes * 60
        self._locks: dict[int, threading.Lock] = {}  # per-chat 文件锁

    def append(self, chat_id: int, role: str, content: str,
               msg_type: str = "TEXT", ok: bool = True) -> None:
        """追加消息:写文件 + 更新内存 hot cache。"""
        entry = {"ts": time.time(), "role": role, "content": content,
                 "msg_type": msg_type, "ok": ok}
        path = self._base / str(chat_id) / "chat.jsonl"
        with self._file_lock(chat_id):
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        hot = self._hot.setdefault(chat_id, [])
        hot.append(entry)
        if len(hot) > self._hot_size:
            hot.pop(0)  # 内存只留最近 N 条,文件保留全量

    def get_context(self, chat_id: int, limit: int = 20) -> list[dict]:
        """返回最近 N 条消息:优先内存,miss 时从文件尾读。"""
        if chat_id in self._hot:
            return self._hot[chat_id][-limit:]
        # Cold miss:从文件 tail 读
        return self._read_tail(chat_id, limit)

    def clear(self, chat_id: int) -> None:
        """写分隔符,不删文件(可审计)。"""
        sep = f"--- cleared at {time.time()} ---"
        with self._file_lock(chat_id):
            with open(self._base / str(chat_id) / "chat.jsonl", "a",
                      encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), "role": "system",
                                    "content": sep}) + "\n")
        self._hot.pop(chat_id, None)

    def _read_tail(self, chat_id: int, limit: int) -> list[dict]:
        """用 deque(maxlen=limit) 从文件尾读。"""
        from collections import deque
        path = self._base / str(chat_id) / "chat.jsonl"
        if not path.exists():
            return []
        buf = deque(maxlen=limit)
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("---"):
                    buf.append(json.loads(line))
        result = list(buf)
        self._hot[chat_id] = result[-self._hot_size:]  # 回填内存
        return result

    def _file_lock(self, chat_id: int) -> threading.Lock:
        if chat_id not in self._locks:
            self._locks[chat_id] = threading.Lock()
        return self._locks[chat_id]
```

**双层缓存的优势**:

| 维度 | 纯内存 | 纯文件 | 双层(本设计) |
|------|--------|--------|--------------|
| 重启后历史 | ❌ 丢失 | ✅ 恢复 | ✅ 恢复 |
| 读取延迟 | <1μs | ~1ms/100条 | <1μs(hot)/~1ms(cold) |
| 内存占用 | N条×M用户 | 0 | N条×活跃用户 |
| 可审计 | ❌ | ✅ | ✅ |
| 并发写入 | 需锁 | 文件锁即可 | per-chat 锁 |

**TTL 与归档**:超过 30 分钟无活动的 chat 目录,`index.json` 标记为 stale;超过 7 天的目录可压缩归档到 `memories/telegram_sessions_archive/<chat_id>.tar.gz`(由 `review_cron.py` 顺带执行)。

### 4.3 与 AgentCore 的衔接

AgentCore 内部已有 `ShortTerm` 记忆（`self._short.append()` + `self._short.recent(10)`），`_call_llm()` 自动注入最近 10 条历史。但 ShortTerm 是全局单例，不区分 chat_id。

**方案**：Telegram 层维护 per-chat 的 `ChatCache` + `SessionState`（§4.6），在调 `agent.handle()` 前，将当前 chat 的缓存上下文以 preamble 形式拼接到 query 前面：

```python
# NL handler 伪代码
state = session_manager.get_or_create(msg.chat_id)
context = chat_cache.get_context(msg.chat_id)
preamble = "\n".join(f"[{m['role']}] {m['content']}" for m in context[:-1])
query = f"{preamble}\n\n[current question] {current_message}" if preamble else current_message
result = agent.handle(query)  # routing .* → LLM fallback
# 更新会话状态
chat_cache.append(msg.chat_id, "user", current_message)
chat_cache.append(msg.chat_id, "assistant", json.dumps(result, ensure_ascii=False))
state.updated_at = time()
```

这样 LLM 能看到对话历史，同时不侵入 AgentCore 内部逻辑。`SessionState` 额外追踪 `pending_action`，支持多轮交互流（详见 §4.6）。

## 4.4 消息类型定义（MsgType + ProcessCategory + IncomingMessage）

当前 `agent.handle(query: str)` 把一切当文本处理，无法区分 Telegram 消息的多种入口类型。需要定义统一的消息类型协议，让 Dispatcher → Queue → Worker 全链路类型安全。

### 4.4.0 消息分类维度（新增 ProcessCategory）

`MsgType` 描述**消息来源形态**（命令/文本/URL/回调/文件），`ProcessCategory` 描述**执行耗时与处理路径**。两者正交,任一消息同时归属一个 `MsgType` 和一个 `ProcessCategory`。分离这两个维度避免把"形态"与"执行模型"耦合死,例如 `/calc 2+2` 是 COMMAND 但属于 INSTANT,`/fetch <url>` 是 COMMAND 但属于 LONG,`/getfile path` 是 COMMAND 也属于 LONG。

| ProcessCategory | 耗时量级 | 执行路径 | 典型场景 | 失败回滚 |
|-----------------|----------|----------|----------|----------|
| `INSTANT` | <2s | 主进程内 `agent.handle()` + `threading.Lock` 串行化 | `/calc`、`lookup`、`tags`、`list`、自然语言查询命中本地索引 | 返回 error 信封 |
| `LONG` | 秒~分钟 | 派生子进程 `WorkerChild` 执行,主循环不阻塞 | `/fetch`、`/getfile`、文件上传下载、`/build`、`/ingest`、`/pipeline`、`/review` | 杀进程 + 通知用户 |
| `INTERACTIVE` | 多轮 | 不立即调 agent,设置 `pending_action` 等用户确认 | `/clear` 后的"确认删除? [是/否]"、文件上传后"是否入库?" | 超时清空 pending |

**为何三档而非二档**:若只分 INSTANT/LONG,多轮确认流(上传文件后问是否入库)只能硬塞进 INSTANT(阻塞主循环)或 LONG(派生进程但进程其实只是等用户输入,浪费资源)。INTERACTIVE 显式建模"等用户"状态,让 `pending_action` 成为 SessionManager 的一等公民,避免确认流污染执行池。

### 4.4.1 消息类型枚举

```python
from enum import Enum, auto

class MsgType(Enum):
    """消息来源形态:描述消息是怎么进来的,不描述怎么执行。"""
    COMMAND = auto()      # /calc 2+2, /fetch url, /getfile path ...
    TEXT = auto()         # 自然语言查询(非 / 开头,非 URL)
    URL = auto()          # 纯 URL 消息(正则 ^https?://\S+ 匹配)
    CALLBACK = auto()     # inline keyboard 按钮回调
    FILE = auto()         # 用户上传文件(document/photo/audio/video/voice)

class ProcessCategory(Enum):
    """执行耗时与处理路径:INSTANT 主进程内 / LONG 派生子进程 / INTERACTIVE 等用户多轮。"""
    INSTANT = auto()
    LONG = auto()
    INTERACTIVE = auto()
```

### 4.4.2 统一消息信封

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class IncomingMessage:
    """Telegram 入站消息的统一表示,贯穿 Dispatcher → Queue → Worker 全链路。"""
    chat_id: int
    user_id: int
    msg_type: MsgType
    text: str                           # 原始文本(command 含 /,URL 为链接,FILE 为文件名)
    raw: dict = field(default_factory=dict)  # 原始 Telegram update dict(保留 file_id 等)
    timestamp: float = 0.0
    # 仅 CALLBACK 类型使用
    callback_data: str | None = None    # inline button 的 callback_data
    # 派生字段:由 __post_init__ 根据 msg_type + text 推导,不接受外部传入
    category: ProcessCategory = field(default=ProcessCategory.INSTANT, init=False)
    # LONG 任务子进程执行完毕后的回执(主进程读取后塞回 IncomingMessage,供 ResponseFormatter 使用)
    worker_result: dict | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.category = _classify_category(self)

    @property
    def is_command(self) -> bool:
        return self.msg_type == MsgType.COMMAND

    @property
    def is_long_running(self) -> bool:
        """是否需要派生子进程执行。"""
        return self.category == ProcessCategory.LONG

    @property
    def is_interactive(self) -> bool:
        """是否进入多轮确认流。"""
        return self.category == ProcessCategory.INTERACTIVE

    @property
    def query_for_agent(self) -> str:
        """转换为 agent.handle() 可消费的 query 字符串。"""
        if self.msg_type == MsgType.COMMAND:
            return self.text[1:]  # 剥离 / 前缀
        if self.msg_type == MsgType.URL:
            return f"fetch {self.text}"
        return self.text
```

### 4.4.3 Dispatcher 分类逻辑

```python
import re

_URL_RE = re.compile(r'^https?://\S+$', re.IGNORECASE)

# 长耗时命令集合:这些 COMMAND 需要派生子进程,不能阻塞主循环
_LONG_COMMANDS: frozenset[str] = frozenset({
    "/getfile", "/fetch", "/crawl", "/抓取", "/下载",
    "/build", "/rebuild", "/update",
    "/ingest", "/pipeline", "/reindex", "/unindex",
    "/review", "/evolve", "/reflect",
})

# 交互式命令集合:设置 pending_action,等用户后续确认
_INTERACTIVE_COMMANDS: frozenset[str] = frozenset({
    "/clear",  # 需用户确认是否清空会话
})

def _classify_category(msg: "IncomingMessage") -> ProcessCategory:
    """根据 MsgType + text 推导 ProcessCategory。"""
    if msg.msg_type == MsgType.FILE:
        # 文件上传/下载/落地都是 IO 密集 + 可能触发 pipeline,统一 LONG
        return ProcessCategory.LONG
    if msg.msg_type == MsgType.URL:
        # 纯 URL 等价 /fetch,必走子进程
        return ProcessCategory.LONG
    if msg.msg_type == MsgType.COMMAND:
        cmd_root = msg.text.split()[0].lower() if msg.text else ""
        if cmd_root in _LONG_COMMANDS:
            return ProcessCategory.LONG
        if cmd_root in _INTERACTIVE_COMMANDS:
            return ProcessCategory.INTERACTIVE
        return ProcessCategory.INSTANT
    # TEXT 与 CALLBACK 默认 INSTANT(CALLBACK 若触发 LONG 动作,由 CallbackRouter 二次分类)
    return ProcessCategory.INSTANT

def classify_message(update: dict) -> IncomingMessage | None:
    """将 Telegram Bot API update 转为 IncomingMessage。"""
    msg = update.get("message") or update.get("callback_query", {}).get("message")
    if not msg:
        return None

    chat_id = msg["chat"]["id"]
    user_id = msg.get("from", {}).get("id", 0)
    text = msg.get("text", "")
    ts = msg.get("date", 0)

    # callback_query(按钮回调)
    cb = update.get("callback_query")
    if cb:
        return IncomingMessage(
            chat_id=chat_id, user_id=user_id,
            msg_type=MsgType.CALLBACK,
            text=cb.get("data", ""),
            raw=update, timestamp=ts,
            callback_data=cb.get("data"),
        )

    # 文件上传
    for file_key in ("document", "photo", "audio", "video", "voice"):
        if file_key in msg:
            return IncomingMessage(
                chat_id=chat_id, user_id=user_id,
                msg_type=MsgType.FILE,
                text=msg.get("caption", ""),  # 文件可能带 caption
                raw=update, timestamp=ts,
            )

    # 命令
    if text.startswith("/"):
        return IncomingMessage(
            chat_id=chat_id, user_id=user_id,
            msg_type=MsgType.COMMAND,
            text=text, raw=update, timestamp=ts,
        )

    # 纯 URL
    if _URL_RE.match(text.strip()):
        return IncomingMessage(
            chat_id=chat_id, user_id=user_id,
            msg_type=MsgType.URL,
            text=text.strip(), raw=update, timestamp=ts,
        )

    # 自然语言
    if text:
        return IncomingMessage(
            chat_id=chat_id, user_id=user_id,
            msg_type=MsgType.TEXT,
            text=text, raw=update, timestamp=ts,
        )

    return None
```

### 4.4.4 类型驱动的处理路由

| MsgType | ProcessCategory | 处理器 | 执行模型 | agent query 构造 |
|---------|-----------------|--------|----------|------------------|
| `COMMAND` | `INSTANT` | CommandMapper | 主进程 `agent.handle()` + Lock | `text[1:]` 剥离 `/` |
| `COMMAND` | `LONG` | CommandMapper → WorkerChild | 派生子进程,exit code + stdout JSON 回传 | `text[1:]` |
| `COMMAND` | `INTERACTIVE` | SessionManager.set_pending | 不立即调 agent,写 `pending_action` 到 session.json | — |
| `TEXT` | `INSTANT` | NLHandler | 主进程 `agent.handle()` + Lock | 拼接 ChatCache 上下文 preamble |
| `URL` | `LONG` | URLHandler → URLWorkerChild | 派生子进程,完成下载+入库+回执 | `f"fetch {text}"` |
| `CALLBACK` | `INSTANT` | CallbackRouter | 主进程读取 `pending_action` 并执行 | 按 `callback_data` 路由 |
| `FILE` | `LONG` | FileHandler → FileWorkerChild | 派生子进程,getFile API+HTTPS 下载+落地+写 TelegramFileRegistry | 不调 agent |

**设计要点**:`category` 是 `init=False` 的派生字段,由 `__post_init__` 调 `_classify_category` 推导。调用方无法手动覆盖(避免误传 `INSTANT` 给一个 `/fetch` 命令,导致主循环被阻塞)。如果某条消息的 `ProcessCategory` 在路由表里找不到对应行,Dispatcher 直接拒绝并返回 error 信封,**fail closed** 而非猜测执行。

## 4.5 沟通协议（BotResponse）

AgentCore 返回统一信封 `{"ok": bool, "result": Any, "error": str|null}`，但 `result` 的类型因 skill 而异（dict / list / str / float）。Telegram 端需要一层协议将 raw dict 转换为 Telegram 可发送的格式。

### 4.5.1 BotResponse 协议定义

```python
from dataclasses import dataclass

@dataclass
class BotResponse:
    """AgentCore 输出 → Telegram 可发送格式的适配层。"""
    text: str                              # MarkdownV2 或 HTML 格式文本
    parse_mode: str = "MarkdownV2"         # Telegram 解析模式
    reply_markup: dict | None = None       # inline keyboard JSON（按钮）
    split_long: bool = True               # 超过 4096 字符自动分段
    disable_notification: bool = False     # 静默发送
```

### 4.5.2 ResponseFormatter

```python
class ResponseFormatter:
    """将 agent.handle() 的 raw dict 转换为 BotResponse。"""

    MAX_CHARS = 4096

    @classmethod
    def format(cls, result: dict, msg: IncomingMessage) -> BotResponse:
        if not result.get("ok"):
            return cls._format_error(result.get("error", "unknown error"))

        data = result.get("result")
        if isinstance(data, (int, float)):
            return cls._format_number(data)
        if isinstance(data, list):
            return cls._format_list(data)
        if isinstance(data, dict):
            return cls._format_dict(data, msg)
        return cls._format_text(str(data) if data else "(empty)")

    @classmethod
    def _format_error(cls, error: str) -> BotResponse:
        return BotResponse(text=f"❌ `{error}`")

    @classmethod
    def _format_number(cls, n) -> BotResponse:
        return BotResponse(text=f"✅ result: `{n}`")

    @classmethod
    def _format_list(cls, items: list) -> BotResponse:
        if not items:
            return BotResponse(text="_no matches_")
        lines = [f"📄 {len(items)} matches:\n"]
        for i, item in enumerate(items[:20], 1):
            title = item.get("title", item.get("path", str(item)))[:60]
            lines.append(f"{i}. {title}")
        if len(items) > 20:
            lines.append(f"\n_...and {len(items) - 20} more_")
        return cls._maybe_split("\n".join(lines))

    @classmethod
    def _format_dict(cls, data: dict, msg: IncomingMessage) -> BotResponse:
        # fetch 结果 → 带确认按钮
        if "filepath" in data and "sync" not in data:
            return BotResponse(
                text=cls._fetch_summary(data),
                reply_markup=cls._confirm_keyboard(
                    f"confirm_ingest:{data['filepath']}"
                ),
            )
        # ingest 结果
        if "total" in data and "ok" in data:
            return BotResponse(
                text=f"✅ Ingested: {data['ok']}/{data['total']} files"
            )
        # 通用 dict
        return cls._maybe_split(
            f"```json\n{json.dumps(data, ensure_ascii=False, indent=2)[:2000]}\n```"
        )

    @classmethod
    def _format_text(cls, text: str) -> BotResponse:
        return cls._maybe_split(text)

    @classmethod
    def _maybe_split(cls, text: str) -> BotResponse:
        """超 4096 字符时标记分段。"""
        if len(text) <= cls.MAX_CHARS:
            return BotResponse(text=text)
        return BotResponse(text=text, split_long=True)

    @staticmethod
    def _confirm_keyboard(callback_data: str) -> dict:
        return {
            "inline_keyboard": [[
                {"text": "📥 确认入库", "callback_data": callback_data},
                {"text": "❌ 忽略", "callback_data": "cancel"},
            ]]
        }

    @staticmethod
    def _fetch_summary(data: dict) -> str:
        title = data.get("title", "")[:40]
        chars = data.get("chars", 0)
        links = data.get("links_count", 0)
        return f"✅ Fetched: *{title}*\n{chars} chars, {links} links"
```

### 4.5.3 协议职责

| 职责 | 说明 |
|------|------|
| 类型适配 | `result` 的 dict/list/str/float → MarkdownV2 文本 |
| 长消息分段 | Telegram 单条上限 4096 字符，超长自动分段发送 `(1/N)` |
| 交互按钮 | fetch 完成后附 "确认入库" 按钮，用户点击 → CALLBACK 消息 |
| 错误友好化 | `{"ok": false}` → `❌ error message` 而非 raw JSON |
| 结果摘要 | list[dict] → `📄 N matches: 1. title...` 而非 raw JSON dump |

## 4.6 Per-Chat 状态机（SessionManager）

当前 `ShortTerm` 是全局单例,不区分 chat_id,A 的对话会污染 B 的上下文。Telegram 场景需要 per-chat 的会话状态,支持多轮交互流。§4.2 已把对话历史持久化到 `memories/telegram_sessions/<chat_id>/`,本节的 `SessionState` 与之同目录,但负责"正在做什么"(pending action)而非"说了什么"(history)。

### 4.6.1 设计原则

- **轻量级**:不需要复杂状态机框架(如 `transitions` 库),用 dataclass + 简单状态字段
- **per-chat 隔离**:每个 chat_id 独立目录 `memories/telegram_sessions/<chat_id>/`,互不干扰
- **文件持久化**:`session.json` 落地,Bot 重启后 pending 状态不丢失(用户可在 Bot 崩溃后继续未完成的确认流)
- **TTL 过期**:30 分钟无活动标记 stale,7 天后由 `review_cron` 归档为 tar.gz
- **多轮交互**:支持 `fetch → 确认入库 → ingest` 这种需要用户确认的流程

### 4.6.2 SessionState 定义

```python
from dataclasses import dataclass, field, asdict
from time import time
from pathlib import Path
import json
import threading

@dataclass
class SessionState:
    """Per-chat 会话状态,持久化到 session.json。"""
    chat_id: int
    pending_action: str | None = None      # 等待用户确认的动作
    pending_data: dict | None = None       # 动作所需的数据
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)
    message_count: int = 0                 # 该会话累计消息数(含已清除的)
    # 非持久化字段(运行期缓存)
    _dirty: bool = field(default=False, init=False, repr=False)

    def is_idle(self) -> bool:
        """无 pending 动作 = 空闲态。"""
        return self.pending_action is None

    def set_pending(self, action: str, data: dict) -> None:
        """进入等待确认态。"""
        self.pending_action = action
        self.pending_data = data
        self.updated_at = time()
        self._dirty = True

    def clear_pending(self) -> None:
        """回到空闲态。"""
        self.pending_action = None
        self.pending_data = None
        self.updated_at = time()
        self._dirty = True

    def to_dict(self) -> dict:
        """序列化(排除 _dirty 等运行期字段)。"""
        d = asdict(self)
        d.pop("_dirty", None)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SessionState":
        """反序列化(忽略未知字段,前向兼容)。"""
        known = {f.name for f in cls.__dataclass_fields__.values() if f.init}
        return cls(**{k: v for k, v in d.items() if k in known})
```

### 4.6.3 SessionManager(文件持久化)

```python
class SessionManager:
    """Per-chat 会话状态管理器,状态落地到 session.json。"""

    def __init__(self, base_dir: str = "memories/telegram_sessions",
                 ttl_minutes: int = 30, max_sessions: int = 200):
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)
        self._ttl = ttl_minutes * 60
        self._max = max_sessions
        # 热缓存:chat_id -> SessionState(避免每次都读文件)
        self._hot: dict[int, SessionState] = {}
        self._locks: dict[int, threading.Lock] = {}
        self._global_lock = threading.Lock()

    def _session_dir(self, chat_id: int) -> Path:
        return self._base / str(chat_id)

    def _session_file(self, chat_id: int) -> Path:
        return self._session_dir(chat_id) / "session.json"

    def _lock(self, chat_id: int) -> threading.Lock:
        with self._global_lock:
            if chat_id not in self._locks:
                self._locks[chat_id] = threading.Lock()
            return self._locks[chat_id]

    def get_or_create(self, chat_id: int) -> SessionState:
        """获取或创建会话状态(优先内存,其次文件,最后新建)。"""
        with self._lock(chat_id):
            if chat_id in self._hot:
                state = self._hot[chat_id]
                state.updated_at = time()
                state._dirty = True
                return state
            state = self._load_from_file(chat_id)
            if state is None:
                if len(self._hot) >= self._max:
                    self._evict_expired()
                state = SessionState(chat_id=chat_id)
                self._ensure_dir(chat_id)
            self._hot[chat_id] = state
            return state

    def get(self, chat_id: int) -> SessionState | None:
        with self._lock(chat_id):
            if chat_id in self._hot:
                return self._hot[chat_id]
            return self._load_from_file(chat_id)

    def save(self, chat_id: int) -> None:
        """显式落盘(在 set_pending / clear_pending 后调用)。"""
        with self._lock(chat_id):
            state = self._hot.get(chat_id)
            if state is None or not state._dirty:
                return
            self._ensure_dir(chat_id)
            tmp = self._session_file(chat_id).with_suffix(".json.tmp")
            tmp.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2))
            tmp.replace(self._session_file(chat_id))
            state._dirty = False

    def clear(self, chat_id: int) -> None:
        """显式清除会话状态(不是 /clear 分隔符,是真正删除 session.json)。"""
        with self._lock(chat_id):
            self._hot.pop(chat_id, None)
            f = self._session_file(chat_id)
            if f.exists():
                f.unlink()

    def _load_from_file(self, chat_id: int) -> SessionState | None:
        f = self._session_file(chat_id)
        if not f.exists():
            return None
        try:
            return SessionState.from_dict(json.loads(f.read_text()))
        except (json.JSONDecodeError, OSError):
            return None  # 损坏文件不阻塞,降级为新建

    def _ensure_dir(self, chat_id: int) -> None:
        self._session_dir(chat_id).mkdir(parents=True, exist_ok=True)

    def _evict_expired(self) -> None:
        """清理内存热缓存中超过 TTL 的会话(文件保留,下次访问会重读)。"""
        now = time()
        expired = [
            cid for cid, s in self._hot.items()
            if now - s.updated_at > self._ttl
        ]
        for cid in expired:
            state = self._hot.pop(cid)
            if state._dirty:
                self._save_unsafe(cid, state)

    def _save_unsafe(self, chat_id: int, state: SessionState) -> None:
        self._ensure_dir(chat_id)
        tmp = self._session_file(chat_id).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2))
        tmp.replace(self._session_file(chat_id))
```

**原子写**:`tmp + rename` 保证 Bot 崩溃时不会留下半写 `session.json`。**前向兼容**:`from_dict` 过滤未知字段,未来加字段不破坏旧 session 文件。

### 4.6.4 状态流转示例

```
场景: 用户发送 URL → bot 抓取 → 用户确认入库

用户: https://example.com/article
  │
  ▼
MsgType.URL (category=LONG) → URLHandler → URLWorkerChild (子进程)
  │ 子进程内: agent.handle("fetch https://example.com/article")
  │ → {"ok": true, "result": {"filepath": "...", "title": "..."}}
  │ 子进程退出,exit code 0,stdout 输出 result JSON
  │
  ▼
主进程读取 stdout → ResponseFormatter → BotResponse(
    text="✅ Fetched: Article Title\n5000 chars",
    reply_markup={"inline_keyboard": [[
        {"text": "📥 确认入库", "callback_data": "confirm_ingest:rag/corpus/xxx.md"},
        {"text": "❌ 忽略", "callback_data": "cancel"},
    ]]}
)
  │
  ▼
SessionState.set_pending("await_ingest_confirm", {"filepath": "..."})
SessionManager.save(chat_id)  ← 写 session.json
  │
  ▼ (用户点击 "确认入库" 按钮)

MsgType.CALLBACK → CallbackRouter
  │ callback_data = "confirm_ingest:rag/corpus/xxx.md"
  │ → 解析 action=confirm_ingest, path=rag/corpus/xxx.md
  │ → category=LONG → CommandMapper → WorkerChild
  │ → 子进程内 agent.handle(f"ingest {path}")
  │ → {"ok": true, "result": {"total": 1, "ok": 1, ...}}
  │
  ▼
SessionState.clear_pending()
SessionManager.save(chat_id)  ← 写 session.json
ResponseFormatter → BotResponse(text="✅ Ingested: 1/1 files")
```

### 4.6.5 状态机状态图

```
                    ┌─────────┐
     用户发消息 ───▶ │  IDLE   │ ◀─── TTL 过期 / /clear
                    └────┬────┘
                         │
                    需要确认的操作
                    (fetch 完成、
                     大文件上传等)
                         │
                         ▼
                    ┌──────────────────┐
                    │ PENDING_CONFIRM  │
                    │                  │
                    │ pending_action=  │
                    │   "await_ingest" │
                    │ pending_data=    │
                    │   {"filepath":..}│
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
         用户点确认      用户点忽略      用户发新消息
              │              │              │
              ▼              ▼              ▼
         执行动作      清除 pending   清除 pending
         → IDLE       → IDLE        处理新消息 → IDLE
              │              │              │
              └──────────────┴──────────────┘
                     每次 state 变更
                     都 save(chat_id) 落盘
```

### 4.6.6 与 ChatCache 的关系

| 组件 | 职责 | 存储位置 | 持久化 |
|------|------|----------|--------|
| `ChatCache` (§4.2) | 对话历史(role/content 列表),供 LLM 上下文 | `memories/telegram_sessions/<chat_id>/chat.jsonl` | JSONL 追加写 |
| `SessionState` (§4.6) | 会话状态(pending action/data),供多轮交互 | `memories/telegram_sessions/<chat_id>/session.json` | JSON 原子覆盖 |
| `SessionManager` | 管理 SessionState 生命周期(TTL/evict/save) | 内存热缓存 + 文件冷存储 | 双层 |

两者互补:ChatCache 记录"说了什么",SessionState 记录"正在做什么"。SessionManager 统一管理生命周期,且与 ChatCache 共享 `<chat_id>/` 目录,Bot 重启后可一次性恢复全部状态。

### 4.6.7 目录布局总览

```
memories/telegram_sessions/
├── index.json                          # 全局索引:chat_id → {created_at, updated_at, msg_count}
├── 123456789/                          # chat_id 目录
│   ├── chat.jsonl                      # 对话历史(ChatCache, §4.2)
│   ├── session.json                    # 会话状态(SessionState, §4.6.2)
│   └── summary.md                      # 可选:LLM 生成的会话摘要(§4.3)
├── 987654321/
│   ├── chat.jsonl
│   └── session.json
└── archive/                            # 7 天前归档(review_cron 负责)
    └── 20260701_123456_123456789.tar.gz
```

`index.json` 由 SessionManager 维护,供 TTL 扫描快速遍历所有会话(不进 `<chat_id>/` 目录),避免 `os.listdir` 在会话数大时变慢。

## 5. 线程安全与消息队列

### 5.1 问题分析

AgentCore **非线程安全**:`ShortTerm` JSON 写、`CacheGuard` SQLite 写、`LongTerm` SQLite 写均无锁。`server.py` 已用 `threading.Lock` 串行化。Telegram 场景更复杂:

- **Long polling 是异步的**:多条消息可能同时到达
- **LLM 调用阻塞**:单次 `handle()` 可能 30s+,期间后续消息全部堆积
- **长任务阻塞**:`build similarity edges` 可能几分钟,不能阻塞整个 bot
- **多用户并发**:A 的 `calc` 不应等 B 的 `review` 完成才能执行(虽然 AgentCore 串行限制了并发度,但消息入队不应阻塞)
- **文件 IO 阻塞**:Telegram `getFile` API + HTTPS 下载、`sendDocument` 上传,单文件可达 50MB,同步执行会卡住 worker 数十秒

### 5.2 方案:asyncio.Queue + 单 worker + 子进程分流

不需要 Redis/Celery 等重量级方案——单进程内 `asyncio.Queue` 处理 INSTANT,`multiprocessing.Process` 处理 LONG。核心设计按 `ProcessCategory` 三分流:

```
Telegram Long Poll (asyncio)
        │
        ▼
┌───────────────────────┐
│  Message Classifier    │  ← 分类为 IncomingMessage(含 category)
│  (MsgType + Category)  │
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐
│  asyncio.Queue        │  ← FIFO 缓冲,不阻塞 poller
│  (maxsize=100)        │
└───────────┬───────────┘
            │
            ▼
┌───────────────────────────────────────────────────────┐
│  Single Worker (asyncio.Task)                          │
│                                                        │
│  按 msg.category 分流:                                  │
│                                                        │
│  ┌── INSTANT ──┐  ┌── LONG ──────────┐  ┌── INTERACTIVE ──┐
│  │             │  │                   │  │                  │
│  │ threading   │  │ Semaphore(max=4)  │  │ SessionManager   │
│  │ .Lock 包裹  │  │   ↓               │  │ .set_pending     │
│  │ agent.handle│  │ multiprocessing   │  │ .save(chat_id)   │
│  │ () 串行执行 │  │ .Process(target=  │  │ 回复确认按钮      │
│  │             │  │   WorkerChild)    │  │                  │
│  │ <2s 返回    │  │   .start()        │  │ 不调 agent        │
│  │             │  │                   │  │                  │
│  │             │  │ proc.wait(120)    │  │                  │
│  │             │  │   超时→proc.kill()│  │                  │
│  │             │  │ exit code + stdout│  │                  │
│  │             │  │   JSON 回传       │  │                  │
│  │             │  │ 回复用户           │  │                  │
│  └─────────────┘  └───────────────────┘  └──────────────────┘
└───────────────────────────────────────────────────────┘
```

**为何 INSTANT 仍用 `threading.Lock` 而非队列串行**:队列串行意味着一个 INSTANT 必须等前一个 LONG 完成(几分钟),用户体验不可接受。`threading.Lock` 串行的是 `agent.handle()` 调用本身,LONG 任务在子进程里跑,主进程的锁几乎不竞争——LONG 任务的主进程开销只是 `proc.start()` 和 `proc.wait()`,毫秒级释放锁。

**为何 LONG 用子进程而非 `run_in_executor` 线程池**:(1) 线程池里跑 `agent.handle()` 仍受 GIL 限制,LLM 调用期间其他 INSTANT 被阻塞;(2) 线程崩溃会污染主进程内存,子进程崩溃只影响自己;(3) 子进程可设硬超时 `proc.wait(timeout=120)` + `proc.kill()`,线程无法强制 kill;(4) 子进程退出即资源释放,线程池长跑会累积 SQLite 连接、文件句柄。

### 5.3 实现

```python
import asyncio
import threading
import multiprocessing as mp
import json
import os
import signal
from concurrent.futures import ThreadPoolExecutor

# ── AgentCore 单例(与 server.py 同模式)──
_agent = None
_agent_lock = threading.Lock()

def _get_agent():
    global _agent
    if _agent is None:
        with _agent_lock:
            if _agent is None:
                from harness.factory import build_agent
                _agent = build_agent()
    return _agent

# ── 消息队列 ──
_msg_queue: asyncio.Queue | None = None

# ── LONG 任务子进程并发上限(信号量)──
_LONG_SEMAPHORE = asyncio.Semaphore(4)  # TELEGRAM_FILE_WORKER_MAX_CONCURRENCY

# ── INSTANT 任务线程池(只跑 agent.handle,池大小=1 保证串行)──
_instant_executor = ThreadPoolExecutor(max_workers=1)

async def _enqueue(msg: IncomingMessage) -> None:
    """Poller 调用:消息入队,不阻塞。"""
    if _msg_queue is None:
        return
    try:
        _msg_queue.put_nowait(msg)
    except asyncio.QueueFull:
        await _reply_text(msg, "⚠️ 消息队列已满,请稍后重试")

async def _worker_loop() -> None:
    """单 worker 消费循环,按 category 分流。"""
    while True:
        msg: IncomingMessage = await _msg_queue.get()
        try:
            if msg.is_interactive:
                await _handle_interactive(msg)
            elif msg.is_long_running:
                await _handle_long(msg)
            else:
                await _handle_instant(msg)
        except Exception as e:
            await _reply_text(msg, f"❌ 内部错误: {type(e).__name__}: {e}")
        finally:
            _msg_queue.task_done()

async def _handle_instant(msg: IncomingMessage) -> None:
    """INSTANT:threading.Lock 包裹 agent.handle(),串行执行。"""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_instant_executor, _call_agent_sync, msg)
    response = ResponseFormatter.format(result, msg)
    await _reply(msg, response)

async def _handle_long(msg: IncomingMessage) -> None:
    """LONG:派生子进程,主循环不阻塞。"""
    async with _LONG_SEMAPHORE:
        await _reply_text(msg, "⏳ 处理中,请稍候...")
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _run_worker_subprocess, msg)
        msg.worker_result = result
        response = ResponseFormatter.format(result, msg)
        await _reply(msg, response)

async def _handle_interactive(msg: IncomingMessage) -> None:
    """INTERACTIVE:设置 pending_action,不调 agent。"""
    state = _sessions.get_or_create(msg.chat_id)
    if msg.text.startswith("/clear"):
        state.set_pending("await_clear_confirm", {})
        _sessions.save(msg.chat_id)
        await _reply_text(msg, "确认清空会话历史?", reply_markup=_confirm_keyboard("confirm_clear"))

def _call_agent_sync(msg: IncomingMessage) -> dict:
    """INSTANT 同步调用,threading.Lock 保证 AgentCore 线程安全。"""
    agent = _get_agent()
    state = _sessions.get_or_create(msg.chat_id)
    query = _build_query_with_context(msg, state)
    with _agent_lock:
        return agent.handle(query)

def _run_worker_subprocess(msg: IncomingMessage) -> dict:
    """LONG 同步派生子进程,返回 result dict。"""
    worker_module = _pick_worker_module(msg)  # file_worker / send_file_worker / url_worker / generic_worker
    proc = mp.Process(target=_worker_entry, args=(worker_module, msg.to_ipc_dict()), daemon=False)
    proc.start()
    try:
        proc.join(timeout=120)  # 硬超时 120s
    except Exception:
        pass
    if proc.is_alive():
        proc.kill()
        proc.join(timeout=5)
        return {"ok": False, "result": None, "error": "worker timeout (120s)"}
    if proc.exitcode != 0:
        return {"ok": False, "result": None, "error": f"worker exit code {proc.exitcode}"}
    # 子进程通过 stdout 输出 result JSON(最后一行)
    # 见 §5.6 详述 IPC 协议
    return _read_worker_stdout(proc)
```

### 5.4 队列溢出与失败策略

| 场景 | 策略 |
|------|------|
| 队列满 (maxsize=100) | 立即回复用户 "⚠️ 繁忙,请稍后重试" |
| INSTANT 超时 (>30s) | `run_in_executor` 不可取消,但 _agent_lock 会自然释放;回复错误 |
| LONG 子进程超时 (>120s) | `proc.kill()` + 回复 "⏱ 任务超时已终止" |
| LONG 子进程崩溃 (exit code ≠ 0) | 回复 "❌ 任务失败,exit code N",不重试 |
| LONG 并发达上限 (4) | 信号量排队,新任务等待;超 60s 仍未拿到信号量则回复 "繁忙" |
| 长任务执行中用户再发消息 | 正常入队排队,不抢占;若该 chat 有 pending_action 则走 INTERACTIVE 分支 |
| Bot 进程重启 | 队列内未处理消息丢失(可接受,Telegram 用户会重发);session.json 持久化可恢复 pending 状态 |

### 5.5 与 server.py 的对比

| 维度 | server.py | telegram_bot.py |
|------|-----------|-----------------|
| 并发模型 | FastAPI + threading.Lock | asyncio.Queue + 单 worker + 子进程分流 |
| 请求来源 | HTTP 客户端(可并发) | Telegram long polling(串行到达) |
| 阻塞处理 | 调用方等待 | 队列缓冲,poller 不阻塞 |
| INSTANT 任务 | `threading.Lock` 串行 | `threading.Lock` 串行(同模式) |
| LONG 任务 | 调用方等待(无分流) | 子进程派生 + 超时 kill |
| 文件 IO | 不涉及 | 子进程隔离,主循环不阻塞 |
| AgentCore 安全 | `threading.Lock` 串行 | INSTANT 走锁,LONG 走子进程,锁几乎不竞争 |

## 5.6 子进程 Worker 详细设计(新增)

LONG 任务的子进程 IPC、生命周期、并发控制在此统一规定。

### 5.6.1 Worker 入口协议

每个 Worker 模块导出统一入口 `run(payload: dict) -> dict`,主进程通过 `multiprocessing.Process` 派生。子进程执行完毕后,通过 **stdout 最后一行** 输出 result JSON,主进程读取并解析。选 stdout 而非 `multiprocessing.Queue` 的原因:stdout 是单向无状态通道,子进程崩溃时已写的 stdout 仍可读;Queue 需要双方存活才能 get/put,主进程 join 后 Queue 可能 deadlock。

```python
# scripts/bot_workers/_worker_base.py(所有 worker 共用,Phase 0 已由 scripts/telegram/ 改名)
import sys, json

def emit_result(result: dict) -> None:
    """子进程执行完毕,通过 stdout 最后一行输出 result。"""
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    sys.stdout.flush()

def worker_main(entry_fn, payload: dict) -> None:
    """统一入口:捕获异常 → emit_result → exit。"""
    try:
        result = entry_fn(payload)
        emit_result(result)
        sys.exit(0)
    except Exception as e:
        emit_result({"ok": False, "result": None, "error": f"{type(e).__name__}: {e}"})
        sys.exit(1)
```

### 5.6.2 四个 Worker 模块

| 模块 | 入口 | 触发场景 | 调用 AgentCore? |
|------|------|----------|-----------------|
| `file_worker.py` | `FileWorkerChild.run` | 用户上传文件(FILE) | 否,直接调 Telegram getFile API |
| `send_file_worker.py` | `SendFileChild.run` | `/getfile path`(COMMAND+LONG) | 否,直接调 Telegram sendDocument API |
| `url_worker.py` | `URLWorkerChild.run` | 纯 URL 消息或 `/fetch`(URL / COMMAND+LONG) | 是,`agent.handle("fetch <url>")` |
| `generic_worker.py` | `GenericWorkerChild.run` | 其他 LONG 命令(`/build`、`/ingest`、`/review`) | 是,`agent.handle(query)` |

### 5.6.3 主进程派生子进程的完整流程

```python
def _run_worker_subprocess(msg: IncomingMessage) -> dict:
    """主进程:派生 → 等待 → 超时 kill → 读 stdout。"""
    worker_module = _pick_worker_module(msg)
    payload = {
        "chat_id": msg.chat_id,
        "user_id": msg.user_id,
        "text": msg.text,
        "msg_type": msg.msg_type.name,
        "raw": msg.raw,  # 含 file_id 等原始 Telegram 字段
    }

    proc = mp.Process(
        target=_worker_entry,
        args=(worker_module, payload),
        daemon=False,  # 非 daemon:确保子进程能 flush stdout
    )
    proc.start()

    # 硬超时控制
    proc.join(timeout=120)
    if proc.is_alive():
        os.kill(proc.pid, signal.SIGTERM)
        proc.join(timeout=5)
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=5)
        return {"ok": False, "result": None, "error": "worker timeout (120s)"}

    # 读取 stdout(子进程已退出,pipe 可读)
    stdout = _read_proc_stdout(proc)
    if proc.exitcode != 0:
        return {"ok": False, "result": None,
                "error": f"worker exit {proc.exitcode}: {stdout[-500:]}"}

    # 解析最后一行 JSON
    lines = [l for l in stdout.splitlines() if l.strip()]
    if not lines:
        return {"ok": False, "result": None, "error": "worker empty stdout"}
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as e:
        return {"ok": False, "result": None,
                "error": f"worker stdout not JSON: {e}"}
```

### 5.6.4 并发控制

- **全局上限**:`asyncio.Semaphore(TELEGRAM_FILE_WORKER_MAX_CONCURRENCY)` 默认 4,防止 50MB 文件下载占满带宽或内存
- **per-chat 上限**:同一 chat_id 最多 2 个并发子进程(防止用户刷屏)
- **排队策略**:信号量 FIFO,超 60s 拿不到则回复 "繁忙,请稍后"

### 5.6.5 资源清理

子进程退出后,主进程必须:
1. `proc.join()` 已完成(回收僵尸进程)
2. 关闭 `proc.stdout` pipe(防止 fd 泄漏)
3. 从 `_running_workers: dict[chat_id, list[proc]]` 移除

Bot 收到 `SIGTERM` 时,主进程先向所有运行中的子进程发 `SIGTERM`,等 5s 后 `SIGKILL`,再自己退出。



## 6. 安全性

本节汇总全部安全控制点,前 6 条为既有要点(已细化),后 7 条针对前轮评估识别的薄弱点给出**方案 / 理由 / 原因 / 优势**。

### 6.1 既有控制点(细化)

- **用户白名单(default-deny)**:`TELEGRAM_ALLOWED_USER_IDS` 环境变量,逗号分隔 Telegram user ID。**空值=拒绝所有人**(非"不限制")。若需公开 Bot,显式设为 `*` 并独立日志审计。见 §6.2.4。
- **Token 保护**:Token 从 `.env` 读取,不硬编码,不进 git。日志输出前经 `TokenRedactor` 过滤(§6.2.5)。
- **超长消息处理**:Telegram 单条消息上限 4096 字符,`ResponseFormatter` 自动分段发送(§4.5)。
- **队列隔离**:`asyncio.Queue(maxsize=100)` 防止消息洪泛导致 OOM;满时拒绝入队并回复用户。
- **会话隔离**:`SessionManager` 按 `chat_id` 隔离,A 的 pending action 和对话历史不会影响 B。session.json 落盘,内存只缓存热会话。
- **路径安全(基础)**:`/getfile` 限定 `rag/corpus/` 根目录,拒绝 `..` 穿越(§3.5.3)。

### 6.2 薄弱点修复(7 项)

#### 6.2.1 路径规范化优先(`Path.resolve()` 前缀检查)

**方案**:
```python
def _safe_corpus_path(raw: str) -> Path | None:
    corpus_root = Path("rag/corpus").resolve()
    target = Path(raw).resolve()
    try:
        target.relative_to(corpus_root)
    except ValueError:
        return None
    if target.is_symlink():
        return None
    return target
```

**理由 / 原因**:`raw` 直接做字符串前缀检查(`raw.startswith("rag/corpus/")`)会被 `rag/corpus/../etc/passwd`(字面前缀合法但实际指向外部)和符号链接绕过。`Path.resolve()` 先把所有 `..`、符号链接、相对路径展开为绝对真实路径,再用 `relative_to(corpus_root)` 验证,杜绝字符串层前缀欺骗。

**优势**:(1) 一次 `resolve()` 同时处理 `..` 穿越 + 符号链接 + 相对路径三种攻击;(2) 异常路径自动 fail(catch ValueError 返回 None),(3) 不依赖字符串比较的边界判断(容易漏 Unicode 同形异义字)。

#### 6.2.2 符号链接拒绝(`is_symlink()` 显式拦截)

**方案**:`Path(name).resolve()` 后再检查 `target.is_symlink()`,双重校验。

**理由 / 原因**:即便 `resolve()` 会跟随符号链接,仍有边角场景:竞态(TOCCTOU)—检查时链接指向合法,读取时被替换。显式 `is_symlink()` 在 `resolve()` 之后复查,拒绝任何本身就是符号链接的路径,堵住竞态窗口。

**优势**:(1) 显式语义"路径本身不能是符号链接",比"链接目标必须合法"更强;(2) 与 §3.5.3 的 `Path(name).name` 原名安全化组合,形成五重路径校验;(3) 让符号链接成为显式禁止项,而非依赖 `resolve()` 副作用。

#### 6.2.3 caption 不作为命令(文件上传 caption 不路由到 agent)

**方案**:`MsgType.FILE` 的 `IncomingMessage.text` 仅记录 caption 用于日志/上下文,不进入 `_classify_category` 的命令分支,不参与 `agent.handle()`。文件落地后若需根据 caption 触发后续动作(如"入库"),必须显式 inline keyboard 二次确认。

**理由 / 原因**:Telegram 允许文件附带 caption 文本,若 Bot 把 caption 当命令解析,攻击者可上传文件 + caption "/getfile /etc/passwd" 触发路径穿越。把 FILE 类型的执行模型锁定为"仅落地,不执行 caption",切断这条注入路径。

**优势**:(1) 攻击面收敛:FILE 消息不可能触发任意 agent 命令;(2) 用户体验仍允许带说明文字,只是不会自动执行;(3) 与 §4.4 的 `ProcessCategory` 设计一致(FILE 永远是 LONG 且仅落地)。

#### 6.2.4 白名单 default-deny(空值拒绝,`*` 显式放行)

**方案**:
```python
def _is_authorized(user_id: int) -> bool:
    raw = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").strip()
    if raw == "*":
        return True  # 显式公开模式
    if not raw:
        return False  # default-deny,不误开放
    allowed = {int(x.strip()) for x in raw.split(",") if x.strip()}
    return user_id in allowed
```

**理由 / 原因**:原方案"空值不限制"默认开放,若运维忘填环境变量,Bot 就对全网公开。default-deny 改为"空值=拒绝所有人",只有显式 `*` 才放行,让"公开 Bot"成为需要刻意配置的选择,而非默认行为。

**优势**:(1) 安全默认值:配置缺失时 fail-closed 而非 fail-open;(2) 显式 `*` 语义清晰,审计可见;(3) 与 `default-deny` 安全原则一致(防火墙、SELinux 等)。

#### 6.2.5 Token 日志脱敏(`logging.Filter` 全局拦截)

**方案**:
```python
class TokenRedactor(logging.Filter):
    def __init__(self, token: str):
        self._token = token
        self._hint = token[:8] + "..." if token else ""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if self._token and self._token in msg:
            record.msg = msg.replace(self._token, self._hint)
        return True

# 启动时
logging.getLogger().addFilter(TokenRedactor(os.getenv("TELEGRAM_BOT_TOKEN", "")))
```

**理由 / 原因**:Bot 崩溃栈、HTTP 请求 dump、Telegram webhook payload 日志都可能无意间输出完整 token。一旦 token 进日志文件,日志可能被运维、CI、外部日志聚合服务看到,等同于泄露。

**优势**:(1) 全局 Filter 一次配置覆盖所有 logger;(2) 不依赖每个调用点记得 redact;(3) 保留 token 前缀用于调试定位("是这个 Bot 的 token 吗");(4) Python stdlib 方案,无额外依赖。

#### 6.2.6 SSRF 内网 IP 黑名单(`fetch` URL 前置校验)

**方案**:
```python
import ipaddress, socket
from urllib.parse import urlparse

_BLOCKED_NETS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

def _is_safe_url(url: str) -> bool:
    host = urlparse(url).hostname
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if any(ip in net for net in _BLOCKED_NETS):
            return False
    return True
```

**理由 / 原因**:`/fetch` 让 Bot 充当 SSRF 跳板:攻击者让 Bot `fetch http://169.254.169.254/latest/meta-data/`(云厂商元数据端点)或 `http://10.0.0.1/admin` 拿到内网敏感数据。元数据端点尤其危险,可泄露 IAM 临时凭证。在 URL 真正被 `requests.get` 之前,先解析 hostname 的全部 A/AAAA 记录,只要任一落在内网段就拒绝。

**优势**:(1) 同时防护 IPv4 + IPv6;(2) 拒绝所有解析结果而非首个(防止 DNS rebinding 攻击者让首次解析公网、二次解析内网);(3) stdlib `ipaddress` 无外部依赖;(4) 黑名单显式列出,审计可见。

#### 6.2.7 文件原名安全化(`Path(name).name` 提取纯名)

**方案**:
```python
from pathlib import Path

def _sanitize_filename(original: str) -> str:
    """提取纯文件名,剥除任何路径前缀。"""
    return Path(original).name or "unnamed"
```

**理由 / 原因**:Telegram `Document.file_name` 由用户上传端控制,可包含 `../`、绝对路径、空字节等。若直接 `Path(corpus_dir) / original` 拼接,`../etc/passwd` 会穿越目录。`Path(original).name` 取 path 的最后一节,剥除所有目录前缀,即便用户上传 `../../etc/passwd` 也只剩 `passwd`,安全落到 corpus 目录内。

**优势**:(1) stdlib 一行解决,无正则误判;(2) 保留原文件名语义(用户看到 `report.pdf` 而非 hash);(3) 与 §6.2.1 的 `resolve()` 前缀检查组合,形成五重路径校验:原名安全化 → 拼接 corpus 目录 → resolve 规范化 → 前缀校验 → 符号链接拒绝。



## 7. 依赖

`pyproject.toml` 新增：

```toml
"python-telegram-bot>=21.0",
```

> `python-telegram-bot` 已包含 `httpx` 依赖，文件下载复用其内置 `Bot.get_file()` + `file.download_to_drive()`，无需额外 HTTP 库。

## 8. 文件清单

### 8.1 主程序与 harness 模块

| 文件 | 说明 |
|---|---|
| `ai-agent-core/telegram_bot.py` | 主程序:守护进程 + Bot 轮询 + 消息分类 + 队列 + Worker 分流 + ResponseFormatter |
| `ai-agent-core/harness/bot/chat_cache.py` | per-chat 对话缓存(双层:内存热 + JSONL 文件冷),供 LLM 上下文 |
| `ai-agent-core/harness/bot/session_manager.py` | per-chat 会话状态管理器(SessionState + SessionManager),文件持久化,支持多轮交互 |
| `ai-agent-core/harness/bot/message_types.py` | 消息类型定义(MsgType + ProcessCategory + IncomingMessage + classify_message) |
| `ai-agent-core/harness/bot/response_formatter.py` | 沟通协议层(BotResponse + ResponseFormatter),agent dict → Telegram 可发送格式 |
| `ai-agent-core/harness/bot/token_redactor.py` | 日志 token 脱敏 Filter(§6.2.5) |
| `ai-agent-core/harness/bot/url_guard.py` | SSRF 内网 IP 黑名单校验(§6.2.6) |
| `ai-agent-core/harness/bot/file_registry.py` | Telegram file_id → filepath 去重注册表(SQLite)(Phase 0 已由 `memories/telegram_file_registry.py` 归位) |
| `ai-agent-core/rag/corpus/telegram/` | 接收文件落地目录(自动创建,.gitkeep) |
| `ai-agent-core/memories/telegram_sessions/` | per-chat 会话持久化目录(`<chat_id>/chat.jsonl` + `session.json` + `index.json`) |
| `ai-agent-core/.env.example` | 追加 `TELEGRAM_*` 环境变量(含 `TELEGRAM_DOWNLOAD_DIR` / `TELEGRAM_MAX_FILE_SIZE_MB` / `TELEGRAM_ALLOWED_FILE_EXTS` / `TELEGRAM_FILE_WORKER_MAX_CONCURRENCY` / `TELEGRAM_WORKER_TIMEOUT_SECONDS`) |
| `ai-agent-core/pyproject.toml` | 追加 `python-telegram-bot>=21.0` 依赖 |
| `ai-agent-core/config/tag_rules.yaml` | (可选)追加 `path_contains: telegram` 规则,让 telegram 子目录文件自动归入 `Telegram/收纳/上传` 分类 |
| `ai-agent-core/.gitignore` | 追加 `rag/corpus/telegram/*` + `memories/telegram_sessions/*/chat.jsonl`(保留 `.gitkeep` 和 `session.json` 示例) |

### 8.2 子进程 Worker 脚本(scripts/bot_workers/)(Phase 0 已由 scripts/telegram/ 改名)

| 文件 | 说明 | 入口 | 触发场景 |
|---|---|---|---|
| `scripts/bot_workers/__init__.py` | 包标记,空文件 | — | — |
| `scripts/bot_workers/_worker_base.py` | Worker 公用入口:统一 `emit_result` + `worker_main` 异常捕获 + stdout JSON IPC 协议 | `worker_main(entry_fn, payload)` | 所有 worker 共用 |
| `scripts/bot_workers/message_types.py` | IPC 消息序列化/反序列化:`IncomingMessage.to_ipc_dict()` / `from_ipc_dict()` | — | 主进程与子进程之间 |
| `scripts/bot_workers/chat_cache.py` | 子进程内对话上下文读取(只读 `memories/telegram_sessions/<chat_id>/chat.jsonl` 尾部 N 条) | `read_recent(chat_id, limit=20)` | url_worker / generic_worker 需要 LLM 上下文时 |
| `scripts/bot_workers/session_manager.py` | 子进程内 session 只读访问(不写,写由主进程负责) | `read_state(chat_id)` | url_worker 检查 pending_action |
| `scripts/bot_workers/file_worker.py` | `FileWorkerChild.run`:Telegram getFile API → HTTPS 下载 → 原名安全化 → 落地 `rag/corpus/telegram/` → 写 TelegramFileRegistry | `FileWorkerChild.run(payload)` | 用户上传文件(MsgType.FILE) |
| `scripts/bot_workers/send_file_worker.py` | `SendFileChild.run`:路径三重校验 → 50MB 检查 → Telegram sendDocument API → 退出 | `SendFileChild.run(payload)` | `/getfile path`(COMMAND+LONG) |
| `scripts/bot_workers/url_worker.py` | `URLWorkerChild.run`:SSRF 校验 → `agent.handle("fetch <url>")` → 返回 result | `URLWorkerChild.run(payload)` | 纯 URL 或 `/fetch`(URL / COMMAND+LONG) |
| `scripts/bot_workers/generic_worker.py` | `GenericWorkerChild.run`:其他 LONG 命令(`/build`、`/ingest`、`/pipeline`、`/reindex`、`/review`、`/evolve`、`/reflect`)→ `agent.handle(query)` | `GenericWorkerChild.run(payload)` | COMMAND+LONG(非 /getfile / /fetch) |
| `scripts/bot_workers/README.md` | 模块概览:Worker 协议、IPC 约定、调试指南、如何本地单独跑 worker | — | 开发者参考 |

### 8.3 测试文件

| 文件 | 说明 |
|---|---|
| `ai-agent-core/tests/test_message_types.py` | MsgType / ProcessCategory / IncomingMessage / classify_message 单测 + `__post_init__` 派生字段验证 |
| `ai-agent-core/tests/test_chat_cache.py` | ChatCache 文件持久化、双层缓存命中、TTL 淘汰、per-chat 锁 |
| `ai-agent-core/tests/test_session_manager.py` | SessionState 序列化/反序列化、session.json 原子写、pending_action 生命周期 |
| `ai-agent-core/tests/test_file_worker.py` | FileWorkerChild 下载流程 mock、原名安全化、file_id 去重 |
| `ai-agent-core/tests/test_send_file_worker.py` | SendFileChild 路径三重校验、50MB 上限、符号链接拒绝 |
| `ai-agent-core/tests/test_url_worker.py` | URLWorkerChild SSRF 拦截、fetch 调用 mock |
| `ai-agent-core/tests/test_security.py` | 7 项安全控制点白盒测试(§6.2.1~6.2.7) |


## 9. 使用流程

```bash
# 1. 在 Telegram 中找 @BotFather 创建 Bot，获取 token
# 2. 配置 .env
echo 'TELEGRAM_BOT_TOKEN=123456:ABC-DEF...' >> .env
echo 'TELEGRAM_ALLOWED_USER_IDS=你的UserID' >> .env

# 3. 安装依赖
pip install -e ".[dev]"

# 4. 启动
python3 telegram_bot.py start

# 5. 在手机 Telegram 中发消息
/calc 2+2           → {"ok": true, "result": 4}
/lookup 大模型       → 搜索结果
今天天气怎么样？      → LLM 对话回复

# 6. 管理
python3 telegram_bot.py status
python3 telegram_bot.py stop
```

## 10. Telegram 端交互示例

```
┌─────────────────────────────────┐
│  用户 (手机)                     │
│                                 │
│  /calc 2 + 2                    │
│  ─────────────────────────────  │
│  ✅ result: 4                   │
│                                 │
│  /lookup RAG                    │
│  ─────────────────────────────  │
│  📄 3 matches:                  │
│  1. AI Coding研发体系(一)...     │
│  2. 个人主权系统...              │
│  3. ...                         │
│                                 │
│  帮我总结一下知识库里关于         │
│  大模型的内容                    │  ← 自然语言
│  ─────────────────────────────  │
│  🤖 知识库中关于大模型的内容      │
│  主要涉及以下几个方面...          │
│                                 │
│  能再详细说说第一点吗？           │  ← 多轮对话
│  ─────────────────────────────  │
│  🤖 好的，第一点指的是...         │
│                                 │
│  /clear                         │
│  ─────────────────────────────  │
│  🧹 对话缓存已清空               │
│                                 │
└─────────────────────────────────┘
```

## 11. 消息格式化策略

AgentCore 返回统一信封 `{"ok": bool, "result": Any, "error": str|null}`，Telegram 端通过 `ResponseFormatter`（§4.5）转换为 `BotResponse` 后发送。

| 场景 | result 类型 | ResponseFormatter 输出 | 附加按钮 |
|------|------------|----------------------|----------|
| 算术 | `float` | `✅ result: 4` | 无 |
| 搜索命中 | `list[dict]` | `📄 N matches:\n1. title...\n2. ...` | 无 |
| 文档内容 | `str` | 原文（超 4096 字符分段，标注 `(1/N)`） | 无 |
| LLM 对话 | `str` | 原文回复 | 无 |
| fetch 结果 | `dict` (含 filepath) | `✅ Fetched: Title\nN chars, M links` | 📥确认入库 / ❌忽略 |
| ingest 结果 | `dict` (含 total/ok) | `✅ Ingested: N/M files` | 无 |
| 错误 | `null` + error | `❌ error message` | 无 |
| 目录树 | `str` | 代码块格式 ``` ... ``` | 无 |
| dict (通用) | `dict` | ` ```json\n{...}\n``` ` (截断 2000 字符) | 视内容而定 |

> 详见 §4.5 沟通协议（BotResponse + ResponseFormatter）的完整实现。

## 12. 异常处理

| 异常场景 | 处理策略 |
|---|---|
| Telegram API 超时 | 自动重试（python-telegram-bot 内置 exponential backoff） |
| AgentCore handle() 异常 | 捕获，返回 `{"ok": false, "error": "..."}` 信封，不会崩溃 |
| LLM API key 未配置 | 指令类正常工作（确定性 skill），NL 类返回明确错误提示 |
| 消息超 4096 字符 | ResponseFormatter 自动分段发送，末尾标注 `(1/N)` |
| Bot 被踢出群组 | 忽略，继续轮询 |
| 队列满 (maxsize=100) | 立即回复用户 "⚠️ 繁忙，请稍后重试"，消息不入队 |
| 单条消息处理超时 (>120s) | worker 超时取消，回复错误，继续处理下一条 |
| 长任务执行中进程重启 | 队列内未处理消息丢失（可接受，Telegram 用户会重发） |
| SessionState TTL 过期 | SessionManager 自动 evict，用户下次发消息创建新会话 |
| CALLBACK 对应的 pending_action 已过期 | 回复 "⚠️ 操作已过期，请重新发起"，清除 pending 状态 |

## 13. 与现有后台进程的协同

```
┌──────────────────────────────────────────────────────────────────┐
│                        机器上同时运行                               │
│                                                                  │
│  background_worker.py   (PID: .watcher.pid)        ← 文件监控     │
│  server.py             (PID: memories/server.pid)  ← HTTP API    │
│  telegram_bot.py       (PID: memories/telegram_bot.pid) ← TG Bot │
│  review_cron.py        (PID: .review_cron.pid)     ← 定时审计     │
│                                                                  │
│  共享: AgentCore 单例（各自进程独立实例）                             │
│  共享: rag/fts_index.db, graph_index.db                          │
│  共享: memories/short_term.json (各自进程独立)                      │
│                                                                  │
│  Telegram Bot 进程内独有:                                          │
│    - asyncio.Queue (消息队列，进程内)                               │
│    - SessionManager (per-chat 状态，进程内内存)                      │
│    - ChatCache (per-chat 对话历史，进程内内存)                       │
│    - ResponseFormatter (协议适配层，无状态)                          │
│                                                                  │
│  互不干扰: 每个进程 build_agent() 独立实例                            │
└──────────────────────────────────────────────────────────────────┘
```

> **注意**：每个后台进程各自 `build_agent()` 创建独立的 AgentCore 实例。SQLite 写入有各自连接，不共享内存状态。Telegram Bot 进程内的 `SessionManager`、`ChatCache`、`asyncio.Queue` 均为进程内内存，不跨进程共享。如需跨进程共享对话上下文或队列状态，需引入外部存储（Redis 等），当前方案中进程内维护即可满足需求。
