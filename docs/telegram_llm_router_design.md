# Telegram LLM Router 设计方案

> 基于现有架构（`telegram_bot.py` + `AgentCore` + `react` skill + MCP servers），
> 让 Telegram Bot 通过 LLM 理解用户意图，动态调用知识库查询 / 知识补充等工具。

---

## 一、设计目标

### 意图 1：查询知识库

```
User (Telegram)                  Bot (常驻进程)
     │                               │
     │  "查询我的简历"                   │
     │  "帮我找一下关于AI的文章"           │
     │  "/lookup python"               │
     └──────────────────────────>       │
                                        │
                                 ┌──────┴──────┐
                                 │  LLM 理解意图  │
                                 │  (DeepSeek)   │
                                 └──────┬──────┘
                                        │
                          ┌─────────────┼─────────────┐
                          │ "knowledge   │ "knowledge  │
                          │  lookup"     │  filter"    │
                          └──────┬──────┘             │
                                 │                    │
                          ┌──────┴──────┐             │
                          │ MCP Server  │             │
                          │ lookup(query)│             │
                          └──────┬──────┘             │
                                 │                    │
                          ┌──────┴──────┐             │
                          │ 返回结果      │             │
                          │ + 原文(可选)  │             │
                          └──────┬──────┘             │
                                 │                    │
                          User ←─┘                    │
                                                      │
                          User ←──────────────────────┘
```

### 意图 2：补充知识库

```
User (Telegram)                  Bot (常驻进程)
     │                               │
     │  "https://example.com/article" │   (URL 消息)
     │  📎 resume.pdf                │   (文件附件)
     │  "帮我抓取这个网页: <url>"      │   (文字命令)
     └──────────────────────────>       │
                                        │
                                 ┌──────┴──────┐
                                 │  LLM 理解意图  │
                                 └──────┬──────┘
                                        │
                    ┌───────────────────┼───────────────────┐
                    │ "fetch_web(url)"  │ "file handler"    │
                    └──────┬───────────┘ └───────┬──────────┘
                           │                     │
                    ┌──────┴──────┐     ┌────────┴────────┐
                    │ 抓取网页→    │     │ 下载文件→        │
                    │ rag/corpus/ │     │ rag/corpus/     │
                    └──────┬──────┘     └────────┬────────┘
                           │                     │
                    ┌──────┴──────┐     ┌────────┴────────┐
                    │ FTS5 索引    │     │ FTS5 索引       │
                    │ graph 索引   │     │ graph 索引      │
                    └──────┬──────┘     └────────┬────────┘
                           │                     │
                    User ←─┘                     │
                    User ←───────────────────────┘
```

---

## 二、当前架构分析

### 现有能力（已就绪）

| 模块 | 功能 | 状态 |
|------|------|------|
| `telegram_bot.py` | 长轮询、`classify_message`、`send_message` | ✅ 可用 |
| `agent.py` `_call_llm` | 支持 DeepSeek (OpenAI 兼容) | ✅ 已实现 |
| `skills/react.py` | ReAct 多步推理（Anthropic tool-use） | ⚠️ 仅支持 Anthropic |
| `mcp/servers/knowledge_server.py` | `lookup` / `filter` / `list` / `tags` | ✅ 可用 |
| `skills/fetch_web_to_md.py` | URL 抓取转 Markdown 入库 | ✅ 可用 |
| `scripts/bot_workers/` | 子进程 Worker（文件下载等） | ✅ 可用 |
| `harness/bot/file_registry.py` | 文件去重注册表 | ⚠️ 待建 |

### 现有问题

| 问题 | 表现 | 根因 |
|------|------|------|
| **无 LLM 意图理解** | "查询我的简历" 直接走 regex → knowledge MCP，无法处理"帮我查简历并发给我"这类复合意图 | routing.yaml 是静态 regex 匹配，不经过 LLM |
| **ReactSkill 只支持 Anthropic** | 用户配的是 DeepSeek，react skill 用不了 | `react.py` 硬编码了 `anthropic.Anthropic()` |
| **文件收发未实现** | 附件 URL 和文件下载没有接入 | FileHandler 在设计中但未实现 |
| **Telegram 连接不稳定** | GFW 阻断 `api.telegram.org` | 需 `TELEGRAM_PROXY` |

---

## 三、设计方案

### 总体架构

```
telegram_bot.py (常驻进程)
    │
    ├── Long Poll Loop ───→ classify_message ───→ IncomingMessage
    │                                                   │
    │                              ┌────────────────────┼────────────────────┐
    │                              │ MsgType.COMMAND    │ MsgType.URL/FILE   │
    │                              │ (/开头)             │ (URL/文件附件)      │
    │                              └────────┬───────────┘                    │
    │                                       │                                │
    │                              ┌────────┴────────┐              ┌────────┴────────┐
    │                              │  ChatSkill       │              │  FileHandler    │
    │                              │  (LLM 意图理解)   │              │  (下载/入库)     │
    │                              │                 │              │                 │
    │                              │  1. LLM 分析意图  │              │  1. 校验白名单    │
    │                              │  2. 调用工具      │              │  2. 下载文件      │
    │                              │  3. 返回结果      │              │  3. 写入 corpus   │
    │                              └────────┬────────┘              │  4. 重建索引      │
    │                                       │                       └────────┬────────┘
    │                                       │                                │
    │                              ┌────────┴────────────────────────────────┴────────┐
    │                              │              AgentCore                          │
    │                              │  ┌──────────┬──────────┬──────────┐             │
    │                              │  │ knowledge │ fetch_web │ file_ops │  ...       │
    │                              │  │ MCP       │ skill     │ skill    │             │
    │                              │  └──────────┴──────────┴──────────┘             │
    │                              └─────────────────────────────────────────────────┘
    │                                       │
    └────────────── sendMessage ────────────┘
```

### 3.1 ChatSkill — LLM 意图理解核心

**新增文件**：`skills/chat.py`

这是本方案的核心新增。它替代当前 `agent.handle()` 的直接 regex 路由，
改为让 LLM 先理解意图，再动态调用工具。

```python
class ChatSkill(Skill):
    """LLM-powered chat skill: understand intent → call tools → return result.

    Supports both Anthropic (tool-use) and OpenAI-compatible (function calling)
    providers, detected automatically from LLM_PROVIDER env var.
    """

    def __init__(self, agent: AgentCore):
        self._agent = agent

    def execute(self, args: dict) -> dict:
        query = args.get("query", "")
        if not query:
            return err("empty query")

        # Step 1: Build tool definitions from registered skills + MCPs
        tools = self._build_tool_definitions()

        # Step 2: Call LLM with tools (function calling)
        response = self._call_llm_with_tools(query, tools)

        # Step 3: If LLM chose to call a tool, execute it
        if response.get("tool_call"):
            tool_result = self._execute_tool(response["tool_call"])
            # Step 4: Give tool result back to LLM for final answer
            final = self._call_llm_with_context(query, response, tool_result)
            return ok({"answer": final, "tool_used": response["tool_call"]["name"]})

        # Step 4: Direct answer (no tool needed)
        return ok({"answer": response.get("text", ""), "tool_used": None})
```

**Tool Definitions**（给 LLM 的函数描述）：

| 工具名 | 描述 | 参数 |
|--------|------|------|
| `knowledge_lookup` | 从知识库搜索信息 | `query: str` — 搜索关键词 |
| `knowledge_filter` | 按标签过滤知识库 | `tags: list[str]` — 标签列表 |
| `knowledge_list` | 列出知识库所有文档 | — |
| `knowledge_tags` | 列出所有标签 | — |
| `fetch_web` | 抓取网页内容并入库 | `url: str` — 网页地址 |
| `get_file` | 从项目发送文件给用户 | `path: str` — 文件相对路径 |
| `calc` | 数学计算 | `expr: str` — 算术表达式 |
| `find_files` | 查找文件 | `pattern: str` — 文件名模式 |
| `grep_search` | 搜索文件内容 | `pattern: str` — 文本模式 |
| `tree_view` | 查看目录树 | `path: str` — 目录路径 |

### 3.2 FileHandler — 文件收发

基于设计文档 §3.5 实现文件接收流程：

```
User sends file/photo/audio in Telegram
    │
    ├─ 1. classify_message → MsgType.FILE
    ├─ 2. 校验 user_id 白名单
    ├─ 3. 校验扩展名白名单 (TELEGRAM_ALLOWED_FILE_EXTS)
    ├─ 4. 校验大小上限 (TELEGRAM_MAX_FILE_SIZE_MB)
    ├─ 5. 立即回复 "⏳ 接收中..."
    ├─ 6. 启动子进程 Worker 下载文件
    │     └─ file_id → getFile → HTTPS GET → 写入 rag/corpus/telegram/
    ├─ 7. 重建 FTS5 + graph 索引
    └─ 8. 回复用户 "✅ 已入库: path"
```

### 3.3 ReactSkill 适配 DeepSeek

修改 `skills/react.py`，让它在 `LLM_PROVIDER=openai` 时使用 OpenAI function calling：

```python
def _call_with_tools(self, messages, tools):
    provider = os.environ.get("LLM_PROVIDER", "anthropic").lower()
    if provider == "openai":
        return self._call_openai(messages, tools)
    return self._call_anthropic(messages, tools)

def _call_openai(self, messages, tools):
    from openai import OpenAI
    client = OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com").rstrip("/") + "/v1",
    )
    resp = client.chat.completions.create(
        model=os.environ.get("OPENAI_MODEL", "deepseek-chat"),
        messages=messages,
        tools=tools,  # OpenAI function calling format
    )
    return resp.choices[0].message
```

### 3.4 Telegram Bot 消息分发改造

修改 `telegram_bot.py` 中的消息处理逻辑：

| 消息类型 | 处理方式 |
|----------|----------|
| `/` 命令 (COMMAND) | 直接走 `agent.handle(query)`（现有 regex 路由） |
| URL 消息 (URL) | 走 FileHandler → `fetch_web` |
| 文件附件 (FILE) | 走 FileHandler → 下载 → 入库 |
| 自然语言 (TEXT) | 走 **ChatSkill** → LLM 意图理解 → 工具调用 |

```python
# 伪代码 — telegram_bot.py 消息分发
if msg.msg_type == MsgType.COMMAND:
    # / 命令走现有 regex 路由
    result = agent.handle(msg.query_for_agent)
elif msg.msg_type in (MsgType.URL, MsgType.FILE):
    # URL/文件走 FileHandler
    result = file_handler.handle(msg)
else:
    # 自然语言走 ChatSkill (LLM 意图理解)
    result = chat_skill.execute({"query": msg.query_for_agent})
```

---

## 四、实现计划

### Phase 1: ChatSkill（LLM 意图理解）

| 步骤 | 文件 | 改动 |
|------|------|------|
| 1.1 | `skills/chat.py` | 新建 ChatSkill，支持 OpenAI function calling |
| 1.2 | `agent.py` | `_parse_skill_args` 添加 `chat` 路由支持 |
| 1.3 | `config/routing.yaml` | 添加 `^chat\b` 路由 → `chat` skill |
| 1.4 | `harness/factory.py` | 注册 ChatSkill |

### Phase 2: Telegram Bot 消息分发

| 步骤 | 文件 | 改动 |
|------|------|------|
| 2.1 | `telegram_bot.py` | 消息分发：COMMAND→agent, URL/FILE→FileHandler, TEXT→ChatSkill |

### Phase 3: FileHandler（文件收发）

| 步骤 | 文件 | 改动 |
|------|------|------|
| 3.1 | `harness/bot/file_handler.py` | 新建 FileHandler（接收文件 → 下载 → 入库） |
| 3.2 | `harness/bot/file_registry.py` | 实现文件去重注册表（SQLite） |
| 3.3 | `telegram_bot.py` | 集成 FileHandler |

### Phase 4: ReactSkill 适配 DeepSeek

| 步骤 | 文件 | 改动 |
|------|------|------|
| 4.1 | `skills/react.py` | 添加 OpenAI function calling 支持 |

---

## 五、与现有架构的关系

```
                    ┌──────────────────────────────────────┐
                    │          Telegram Bot                 │
                    │  (telegram_bot.py)                    │
                    │                                       │
                    │  ┌──────────┐  ┌───────────────┐      │
                    │  │ Long Poll│  │  FileHandler   │      │
                    │  │  Loop    │  │  (Phase 3)     │      │
                    │  └────┬─────┘  └───────┬───────┘      │
                    │       │                │              │
                    │       ▼                ▼              │
                    │  ┌──────────────────────────┐         │
                    │  │     Message Dispatcher    │         │
                    │  │  COMMAND → agent.handle() │         │
                    │  │  URL/FILE → FileHandler   │         │
                    │  │  TEXT    → ChatSkill      │◄── 新增  │
                    │  └────────────┬─────────────┘         │
                    └───────────────┼───────────────────────┘
                                    │
                    ┌───────────────┼───────────────────────┐
                    │    AgentCore (agent.py)                │
                    │               │                        │
                    │        ┌──────┴──────┐                 │
                    │        │  _route()   │                 │
                    │        │  routing.yaml│                 │
                    │        └──────┬──────┘                 │
                    │               │                        │
                    │     ┌─────────┼─────────┐              │
                    │     ▼         ▼         ▼              │
                    │  skill     mcp       llm               │
                    │  ChatSkill◄─┘  knowledge MCP ◄── 新增   │
                    │  (Phase 1)     fetch_web               │
                    │                file_ops                │
                    └───────────────────────────────────────┘
```

---

## 六、关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| LLM 意图理解方式 | **OpenAI function calling** | 用户使用 DeepSeek，兼容 OpenAI API |
| 消息分发位置 | **telegram_bot.py** | 保持 AgentCore 通用性，Bot 层做分发 |
| 工具定义粒度 | **细粒度**（knowledge_lookup / knowledge_filter 分开） | LLM 更容易理解每个工具的职责 |
| 文件处理方式 | **子进程 Worker**（复用现有 `scripts/bot_workers/`） | 内存隔离、崩溃隔离、超时可控 |
| 会话管理 | **SessionManager**（已有 `harness/bot/session_manager.py`） | 支持多轮上下文 |

---

## 七、路由配置示例（routing.yaml）

```yaml
# 新增 chat 路由 — LLM 意图理解（优先级高于 .* 兜底）
- intent: '^chat\s+'
  tool_type: "skill"
  tool_name: "chat"
  fallback: null

# 注意：chat 路由放在 .* 兜底之前，
# Telegram Bot 在消息分发时自行决定走 chat 还是 regex
```

---

## 八、ChatSkill 调用示例

```
User: "查询我的简历"

→ ChatSkill.execute({"query": "查询我的简历"})
  → LLM (DeepSeek) 收到工具列表：
      1. knowledge_lookup(query) — 知识库搜索
      2. knowledge_filter(tags) — 标签过滤
      3. fetch_web(url) — 网页抓取
      ...
  → LLM 决定调用 knowledge_lookup(query="我的简历")
  → ChatSkill 执行 knowledge MCP lookup
  → 返回结果给 LLM
  → LLM 组织最终回答
  → "我找到了你的简历，内容如下：..."
```

```
User: "https://example.com/article"

→ classify_message → MsgType.URL
→ FileHandler 处理：
  1. 校验 URL 格式
  2. 调用 fetch_web skill
  3. 抓取内容写入 rag/corpus/
  4. 回复 "✅ 已抓取并入库"
```
