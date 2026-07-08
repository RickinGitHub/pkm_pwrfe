# ai-agent-core 项目结构

> Token-efficient Agentic Core — 确定性优先路由（cache → skills → MCP → LLM）+ 混合 RAG 检索 + 分级记忆

## 总体架构

```text
用户输入
  ↓
agent.py: AgentCore.handle(query)
  ↓
1. 追加到短期记忆
  ↓
2. 语义缓存检查 ─── 命中 → 直接返回
  ↓ 未命中
3. 路由匹配 routing.yaml（正则）
  ↓
4. ├─ skill → 本地确定性执行（math / file_ops / fetch_web / context / find_ops / grep_ops / tree_ops / pipeline_ops / reflect / review）
   ├─ mcp   → 外部工具调用（knowledge / hybrid_knowledge / file_search）
   └─ llm   → Anthropic API（兜底）
  ↓
5. evaluator 校验信封 + 格式
  ↓ 失败 + fallback=llm → 重试 LLM 路径
  ↓
6. 成功 → 写入 cache + 短期记忆 + 长期三元组
  ↓
返回 {"ok": ..., "result": ..., "error": ...}
```

### 核心设计原则

- **确定性优先**：所有 query 经归一化（`lowercase + 折叠空白`）后按 `config/routing.yaml` 正则匹配；skill 与 MCP 本地执行零 token 消耗
- **信封协议**：所有输出统一 `{"ok": bool, "result": Any, "error": str | None}`，机器可解析、易校验
- **语义缓存**：`SHA256(normalized_query)` 为 key，SQLite 存储，TTL 控制；可选 embedding 语义相似度回退（cosine ≥ 0.85 命中近似 query）
- **分级记忆**：短期（`deque + JSON`）保存对话上下文，长期（SQLite 三元组 `(subject, predicate, object, ts)`）保存事实
- **混合 RAG**：BM25 + 向量检索，min-max 分数归一化后按 `0.5 * bm25 + 0.5 * vector` 融合；中英混合分词（英文按空格 + 中文按 2 字 bigram）
- **共享 CorpusLoader**：`knowledge` 与 `hybrid_knowledge` 两个 MCP Server 共享同一个 `CorpusLoader` 实例，避免重复文件 I/O

---

## 文件树

由 `python3 ai-agent-core/skills/tree_ops.py -L 2 .` 自动生成（在 `pkg/` 根目录执行）：

```text
pkg
├── ai-agent-core/
│   ├── __pycache__/ ...
│   ├── ai_agent_core.egg-info/ ...
│   ├── config/ ...
│   ├── harness/ ...              # 含 factory.py + daemon.py
│   ├── mcp/ ...
│   ├── memories/ ...
│   ├── rag/ ...
│   ├── scripts/ ...
│   ├── skills/ ...               # 含 react.py
│   ├── tests/ ...
│   ├── agent.py
│   ├── background_worker.py
│   ├── server.py                 # Phase 2 — HTTP API (FastAPI + uvicorn)
│   ├── review_cron.py            # Phase 4 — Review 守护进程
│   ├── pyproject.toml
│   └── README.md
├── docs/
│   ├── superpowers/ ...
│   ├── operations.md
│   ├── structure.md
│   └── watcher_pipeline.md
└── rag/
    ├── fts_index.db
    └── graph_index.db

3 directories, 11 files
```

> 注：`...` 表示该目录因深度限制（`-L 2`）被截断，可去掉 `-L` 参数或加大深度查看完整内容。下文「主要文件说明」给出 `ai-agent-core/` 内各文件的逐项注解。

---

## 主要文件说明

### `agent.py` — 核心编排器

无状态的 `AgentCore` 类，是整个系统的入口和流程控制中心。

- **构造函数**接收 5 个路径（rules、routing、cache、short_term、long_term），初始化各模块
- **`handle(query)`** 主入口，执行流程：
  1. 追加 `("user", query)` 到短期记忆
  2. 检查语义缓存（命中则直接返回）
  3. 路由匹配 → 调用对应 skill / mcp / llm
  4. 通过 evaluator 校验输出
  5. 失败时按 `fallback` 配置回退到 LLM
  6. 成功时写入缓存 + 短期记忆 + 长期三元组
- **`bootstrap_memory()`** — 幂等写入项目元数据到长期记忆（name、version、description、architecture、skills、mcp_servers、last_boot）；`ContextSkill` 读取这些字段重建项目简报
- **`_parse_skill_args`** — 把自然语言 query 解析成 skill 的 `args` 字典。支持 `calc`、`stats`、`read/load/show file`、`clean/sanitize file`、`context/brief/resume/status/whoami`、`fetch/crawl`、`reflect`、`review/evolve`，以及 CLI 风格的 `find` / `grep` / `tree` / `find_grep`（各自委托对应的 `_parse_*_args` 静态方法）
- **`_call_knowledge`** — 路由知识查询：`filter [tags]`、`list`、`tags`，或 `lookup`（中英文前缀剥离）
- **`_call_llm`** — 调用 Anthropic API，模型 ID 通过 `ANTHROPIC_MODEL` 环境变量配置。**多轮对话**（P0-1）：`_build_llm_messages` 注入 `short_term.recent(10)` 作为 `user`/`assistant` 历史，最后一条 user 消息被改写为 `rules.prompt_prefix + "\n\nUser query: <q>\nOutput JSON only."`；若历史末条已是当前 query 则原地改写避免重复

### `config/` — 配置层

- **`models.py`** — Pydantic v2 模型，开启 `extra="forbid"` 严格校验。`RulesConfig` 约束 `max_output_tokens ∈ [64, 8192]`，`output_format` 和 `tool_type` 使用 `Literal` 枚举
- **`loader.py`** — YAML 安全加载（`yaml.safe_load`），文件不存在抛 `FileNotFoundError`
- **`rules.yaml`** — 系统规则：角色 `"Senior AI Infrastructure Engineer"`，Token 预算 1024，prompt 强制 JSON 输出
- **`routing.yaml`** — 路由表（按优先级，首条匹配胜出）：
  - `^(calc|compute|what is).*\d` → math_logic
  - `^stats.*` → math_logic
  - `^(context|brief|resume|status|whoami).*` → context（无 fallback）
  - `^(read|load|show|clean|sanitize).*file` → file_ops
  - `^(clean|sanitize).*` → file_ops（无 fallback）
  - `^(ls|dir|glob|file.search|find.files|find files|find file).*` → file_search MCP
  - `^(hybrid|rag|deep.search|semantic).*` → hybrid_knowledge MCP
  - `^(lookup|search|find|filter|list|tags|chunks|chunks_by_cat|查询|搜索|查找|寻找|找|帮我|什么是|怎么|标签|列出|所有).*` → knowledge MCP（含 Phase 7 chunks 入口）
  - `^reflect\s+` → reflect skill（Phase 6）
  - `^(review|evolve)\b` → review skill（Phase 5）
  - `^(fetch|抓取|下载|crawl).*http` → fetch_web
  - `.*` → LLM 兜底

### `harness/` — 防幻觉层

- **`cache_guard.py`** — 语义缓存。Key = `SHA256(lowercase + 折叠空白)`，TTL 默认 3600s。SQLite 存储自动迁移 schema（含 `embedding BLOB` 列）。可选 `embedder` 参数 + `semantic_threshold=0.85` 阈值启用语义相似度回退：精确 hash 未命中时，遍历所有缓存项算余弦相似度，超过阈值即返回
- **`evaluator.py`** — 输出校验器。检查信封 keys `{ok, result, error}` 齐全；`ok=False` 的失败信封直接透传；JSON 模式接受 dict/list/scalar/可解析 JSON 字符串
- **`factory.py`** — **Phase 1** — `build_agent() -> AgentCore` 工厂。把原本内联在 `agent.py:main()` 的 wiring（构造 + 所有 skill/MCP 注册 + `bootstrap_memory()`）抽到独立函数，路径全部从 env 读，默认值与原 `main()` 一致。`server.py` / `review_cron.py` 复用此工厂避免重复 wiring。`main()` 缩到 ~6 行：`build_agent()` → `handle(query)` → `print(json.dumps(...))`
- **`daemon.py`** — **Phase 2** — 守护进程共享工具。从 `background_worker.py` 抽取 PID/信号/pgrep 孤儿清理逻辑，函数签名带 `script_name` + `pid_file_env` 参数，供 `background_worker.py` / `server.py` / `review_cron.py` 三处复用。包含 `write_pid` / `read_pid` / `is_running` / `stop_process` / `start_daemon` / `status_daemon` / `subcommand` 等工具函数

### `rag/` — 知识检索

- **`corpus_loader.py`** — `CorpusLoader`：递归加载 `.txt`/`.md`。可选分块：`chunk=True, chunk_size=1200, chunk_overlap=150`。`reload()` 重新扫描目录。`knowledge` 与 `hybrid_knowledge` 共享同一实例避免重复 I/O
- **`metadata.py`** — `MetadataIndex`：内存索引。从文件名解析 `[tag]`、从 `YYYYMMDD_HHMMSS_` 前缀解析日期、从首个 `#` 标题解析标题、从正文 `**URL**: <...>` 解析源 URL。`filter(tags=, date_from=, date_to=, source_contains=)` 全部 AND 组合
- **`chunker.py`** — `TextChunker`：`paragraph` 策略按双换行分段、合并短段、对超长段在句子边界（`。！？.!?`）切分；`fixed` 策略按滑动窗口 + overlap，并尝试在 CJK/ASCII 句末符处断开。每个 chunk 的 id 形如 `doc.md#0`
- **`tokenizer.py`** — 中英混合分词。CJK 字符按 2 字 bigram（`"查询简历"` → `["查询", "询简", "简历"]`），非 CJK 按空格分词小写化
- **`embedder.py`** — Embedder 工厂。优先级：显式 `model_name` > `EMBEDDING_MODEL` 环境变量 > SHA256 伪嵌入。支持 `sentence-transformers`（如 `all-MiniLM-L6-v2` 384 维、`all-mpnet-base-v2` 768 维）
- **`retriever.py`** — `HybridRetriever`：每次 query 时基于内存 docs 列表重建 BM25 索引，同时调向量搜索，min-max 归一化后按权重 `0.5 * bm25 + 0.5 * vector` 融合，取 top-k
- **`fts_index.py`** — **Phase 1** — SQLite FTS5 虚拟表，`trigram` 分词器，短查询（< 3 字符）走 `instr()` substring 兜底。Upsert 用 `DELETE + INSERT` 绕过 FTS5 PK 限制
- **`graph_index.py`** — **Phase 2** — SQLite `document_graph`（L1/L2/L3/L4 路径，复合主键 `(path, l1, l2, l3)` Multi-homing）+ **Phase 4** `knowledge_edges`（wikilinks）+ **Phase 7** `document_chunks`（L5 chunks）。WAL 模式 + 模块级迁移单例（`_migration_done` set + `_migration_lock`）保证多线程并发写入不丢失
- **`vector_db/store.py`** — 基于 sqlite-vec 的向量存储。`vec0` 虚拟表存 float 向量，搜索返回 `(id, text, 1.0 - distance)`（余弦相似度）。Upsert 用 `DELETE + INSERT` 绕过 vec0 主键限制
- **`corpus/`** — 知识库源文档目录，放 `.txt` / `.md` 文件。`fetch_web_to_md` 默认输出到此目录，抓取后立即可被 `lookup` 检索

### `skills/` — 本地确定性技能

所有技能实现 `execute(args: dict) -> dict` 接口，返回 `{"ok": bool, "result": Any, "error": str | None}` 信封。

- **`base.py`** — `Skill` Protocol 定义 + `ok(result)` / `err(message)` 辅助函数
- **`math_logic.py`** — `calc` 用 `ast.parse(mode="eval")` + 递归 `_safe_eval`（白名单 `BinOp`/`UnaryOp`/`Constant`），拒绝 `__import__('os')` 等 AST 节点；`stats` 返回 mean/sum/count
- **`file_ops.py`** — `read` 读取文件文本，`clean` 去除每行首尾空白并丢弃空行
- **`fetch_web_to_md.py`** — 扩展技能：Web 抓取转 Markdown/JSON/HTML。**默认输出目录为 `rag/corpus/`**，文件名基于原文 title（`<title>.<ext>`，无时间戳前缀），抓取的内容直接进入知识库可被 `lookup` 检索；可通过 `output_path` 参数指定输出**目录**（相对或绝对路径）。支持微信公众号（专用 UA + `js_content` 选择器）与通用网页。支持下载图片（`save_img`，下载到 `<dir>/images/` 并改写 .md URL 为本地路径）、下载文件附件（`save_attachments`，pdf/zip/docx/mp4 等下到 `<dir>/attachments/` 并改写 URL）。`<iframe>`/`<video>`/`<audio>`/`<embed>` 嵌入媒体统一转为可点击 Markdown 链接占位（`[📎 Video](url)`），保留原 URL。提取链接、批量抓取、聊天文本提取 URL 等附加功能。**URL 去重**（P0-2）：构造时可注入 `UrlRegistry`（SQLite），每次成功抓取后记录 URL→filepath；重复抓取同一 URL 时若缓存文件仍存在，直接返回缓存路径并在 result 中标注 `source_type="cached"`、`deduped=True`；`force=True` 跳过去重；缓存文件已丢失则自动重新下载
- **`context.py`** — 上下文恢复技能。读取长期记忆中的项目元数据、最近事实、短期记忆最近对话，组装成结构化项目简报。新会话运行 `python -m agent "context"` 即可恢复上下文
- **`reflect.py`** — **Phase 6** — `ReflectSkill`：向老笔记追加 `## 实践复盘 YYYY-MM-DD` 段，同时更新 frontmatter 的 `revisions` 数组。24h 内同 insight 文本去重（`REFLECT_DEDUP_WINDOW_HOURS` 可配置）。原子写入：`.tmp + os.replace`。路径解析：相对路径 → cwd；短名 → `rag/corpus/<name>`；否则 rglob 整个 corpus
- **`review.py`** — **Phase 5** — `ReviewSkill`：`review [l1] [l2] [l3] [--query "..."] [--max-chars N] [--dry-run] [--no-cache]` 按 L1/L2/L3 分类批量打包全量文档（受 400k chars / ~100k tokens 限流），调 LLM 做"认知审计"。24h 缓存（同 domain+query 复用，`REVIEW_CACHE_DB` 可配置）。与 `lookup` 互补：lookup 毫秒级返回 snippet，review 秒级烧 token 适合周末静思
- **`find_ops.py`** — Linux `find` 风格文件查找（name/regex/type/size/time/max_depth）。已注册为 `find_ops`，路由 `^find\s` → `find <path> [-name X] [-type f|d] [-maxdepth N] [-recursive] [-empty] [-mtime -7]`
- **`grep_ops.py`** — Linux `grep` 风格文本搜索（regex/ignore_case/invert/context_before/after/count/files_with_matches）。已注册为 `grep_ops`，路由 `^grep\b` → `grep <pattern> [path] [-i] [-n] [-r] [-l] [-c] [-v] [-E] [-C N] [-g glob]`
- **`tree_ops.py`** — Linux `tree` 风格目录树展示（max_depth/dirs_only/all_files/show_size/human_size/full_path/pattern/ignore）。已注册为 `tree_ops`，路由 `^(tree|目录树|目录结构)\b` → `tree [path] [-L N] [-d] [-a] [-s] [-h] [-f] [-P pat] [-I pat] [--noreport]`
- **`pipeline_ops.py`** — Unix 管道 skill 组合器 + 知识图谱维护 op。两个 op:① `find_grep`(find + xargs grep,路由 `^find_grep\b`);② `build_similarity_edges`(P1 — 封装 `scripts/build_similarity_edges.build_edges`,`corpus_dir`/`graph_db` 必填,路由 `^(build|rebuild|update)_similarity.*(edge|graph)?\b`)
- **`react.py`** — **Phase 3** — `ReactSkill`：基于 Anthropic tool-use API 的 ReAct 多步推理 skill。构造器接 `agent: AgentCore` 引用，`__init__` 里一次性实例化 `anthropic.Anthropic` 客户端（复用提升 prompt-cache 命中率）。`execute({query, max_steps=5, allowed_tools})` 遍历 `agent._skills` + `agent._mcp.servers` 构建 tool schemas（`skill_<name>` / `mcp_<name>`），循环调用 `messages.create(tools=...)`，对每个 `tool_use` block 走 `agent._call_skill` / `agent._call_mcp` 分发，结果 JSON 截断到 2000 字符后追加 `tool_result` block，`stop_reason=="end_turn"` 或 `max_steps` 触发停止。硬上限 `_MAX_STEPS_HARD_CAP=10`，缺 `ANTHROPIC_API_KEY` → `err()`

### `mcp/` — 协议化工具接入

- **`mcp_client.py`** — 工具注册表。`register(name, tool)` / `list_tools()` 返回排序后的名称列表 / `call(name, args)` 返回信封，捕获 tool 异常转为错误信封
- **`servers/knowledge_server.py`** — 知识库 MCP Server。Ops：
  - `lookup <query>` — FTS5 优先（O(log n)）→ 子串匹配 → BM25 兜底；支持 `tags` 预过滤
  - `filter [tags...]` — 按 tag/date/source 元数据过滤，返回文档列表
  - `list` — 列出所有文档及其元数据
  - `tags` — 列出语料中所有唯一 tag
  - `chunks <path>` — **Phase 7** — 返回某文档的所有 L5 chunks（需注入 `graph_db_path`）
  - `chunks_by_cat l1 [l2] [l3]` — **Phase 7** — 按分类筛选 chunks
- **`servers/hybrid_knowledge_server.py`** — 混合 RAG MCP Server。封装 `HybridRetriever`，自动探测 embedding 维度，懒加载语料。支持 `k` 参数控制返回数量，返回 `hits` 列表 + `top_text`
- **`servers/file_search_server.py`** — 文件搜索 MCP Server。`search` op 递归 glob 匹配，返回 path/size/modified-time，支持 `max_results` 和 `case_sensitive`

### `memories/` — 分级记忆

- **`short_term.py`** — 短期记忆。`deque(maxlen=N)` 滚动窗口，每次 append/clear 都持久化到 JSON 文件。支持跨实例加载（重启后状态保留）。`recent(n)` 返回最近 n 条
- **`long_term.py`** — 长期记忆。SQLite 表 `triplets(subject, predicate, object, ts)`，支持按 subject/predicate 查询，`summarize_as_text()` 返回 `"subject predicate object"` 拼接文本
- **`url_registry.py`** — **P0-2** — URL→filepath 去重注册表。SQLite 表 `url_map(url PK, filepath, title, fetched_at)`，`lookup(url)` 返回 dict 或 None，`record(url, filepath, title)` 用 `ON CONFLICT(url) DO UPDATE` upsert。线程安全（`threading.Lock` + `check_same_thread=False`）。独立于 long_term / graph_index，便于单独替换
- 运行时的 `short_term.json`、`long_term.db`、`cache.db`、`url_map.db` 均被 gitignore

### `tests/` — 测试套件

31 个 pytest 测试文件、357 个用例，覆盖 Phase 1-7 全部模块、P0/P1 缺口补全及 Phase 1-4 主动产出层（factory / HTTP / ReAct / cron）。AAA 模式（Arrange-Act-Assert），描述性命名（`test_<行为>`）。flaky 测试已修复：Phase 4 并发迁移用模块级单例锁（`_ensure_migrated`），Phase 5 缓存用 `autouse` fixture 隔离（`REVIEW_CACHE_DB` env）。`test_e2e.py` 是端到端集成测试，覆盖 math skill / cache 命中 / file_ops / MCP lookup / 记忆状态 / LLM 兜底（无 API key 时返回错误信封）等完整流程。P0-1 `test_p0_multiturn.py` 用 MagicMock + monkeypatch 校验 `_call_llm` 真的把多轮 messages 发给 Anthropic 客户端；P0-2 `test_p0_url_dedup.py` 覆盖去重命中 / force 绕过 / 文件丢失回退 / 抓取后登记；P1 `test_p1_similarity_edges.py` 覆盖 top-k / 自环过滤 / clear 替换 / min_score 过滤 / 空语料，`test_p1_pipeline_similarity_op.py` 覆盖 `pipeline_ops.build_similarity_edges` op 的基本构建 / clear 幂等 / 参数校验。Phase 1-4 新增：`test_factory.py`（build_agent 注册 ≥11 skill + 幂等）、`test_react_skill.py`（单步 tool_use / max_steps 上限 / allowed_tools 过滤 / 缺 API key / 结果截断）、`test_server.py`（/health /query / 并发串行化 / 404）、`test_review_cron.py`（mock ReviewSkill / _next_run / stop_event 退出 / 生命周期）。

### 顶层文件

- **`pyproject.toml`** — Python 3.11+，依赖 pydantic v2 / pyyaml / numpy / rank-bm25 / sqlite-vec / mcp / anthropic / python-dotenv / fastapi / uvicorn。dev 依赖 pytest + pytest-cov + pytest-asyncio + httpx。pytest 配置 `asyncio_mode = "auto"`
- **`.env.example`** — 环境变量模板：`ANTHROPIC_API_KEY`、`ANTHROPIC_MODEL`、`EMBEDDING_MODEL`、`CORPUS_CHUNK_*`、`PIPELINE_CHUNK_*`、`OLLAMA_*`、`REFLECT_DEDUP_WINDOW_HOURS`、`REVIEW_CACHE_DB`、`SERVER_*`、`REVIEW_CRON_*`、`REVIEWS_DIR`、各模块路径
- **`.gitignore`** — 忽略 `.env`、`*.db`、`__pycache__/`、`.venv/`、`.pytest_cache/`、`memories/short_term.json`、`memories/long_term.db`、`memories/review_cache.db`、`memories/server.pid`、`memories/review_cron.pid`、`reviews/*.md`
- **`README.md`** — 安装与使用说明
- **`background_worker.py`** — 后台 watcher 守护进程（文件变更 → FTS5 + graph_index 重跑）。PID/信号/pgrep 模式抽到 `harness/daemon.py`，本文件复用共享工具
- **`server.py`** — **Phase 2** — HTTP API 入口（FastAPI + uvicorn）。模块级 `app = FastAPI()`、`_agent = build_agent()`、`_lock = threading.Lock()`（AgentCore 非线程安全，`/query` 串行化）。端点 `POST /query` body `{"query": str}` → `with _lock: _agent.handle(query)`；`GET /health` → `{"ok": true}`。CLI 子命令 `run/start/stop/restart/status`，PID 文件 `memories/server.pid`，端口 env `SERVER_PORT`（默认 8000）
- **`review_cron.py`** — **Phase 4** — Review 定时守护进程。模式照搬 `background_worker.py`，用 `harness.daemon` 工具。`time.sleep(poll)` 轮询 + `next_run` 比较 + `threading.Event` 停机（不引 APScheduler）。`_run_cycle()` 调 `build_agent()` → 从 `graph_index.db` 查 distinct `l1` → 对每个 l1 调 `ReviewSkill.execute({op:"review", l1:...})` → 报告写 `reviews/YYYYMMDD_HHMMSS_<l1>.md`。配置 `REVIEW_CRON_EVERY_HOURS`（默认 24）等。子命令 `run/start/stop/restart/status`

---

## 关键数据流

### 1. 命中缓存的快速路径

```text
query="calc 2+2"
  → 短期记忆 append
  → cache_guard.get: SHA256("calc 2+2") 命中 → 返回 {"ok": True, "result": 4, ...}
  → 短期记忆 append (assistant)
  → 返回（不写 long_term，因为已命中）
```

### 2. 知识检索流程（Phase 1 起集成 FTS5）

```text
query="lookup python"
  → 路由匹配 knowledge MCP
  → _call_knowledge: 剥离 "lookup" 前缀 → query="python"
  → KnowledgeServer._do_lookup:
      1. FTS5 优先（若注入 FtsIndex）：
         FtsIndex.search("python") → snippet 高亮 + rank 排序
         若有 tag 过滤 → 校验命中 path 在 tag 过滤集内
      2. FTS5 无命中 → 子串匹配 "python" 在所有 docs 中扫描
      3. 仍未命中 → BM25 over 全部 docs，取最高分
  → evaluator 校验信封
  → 写入 cache + short_term + long_term triplet ("user", "asked", "lookup python")
```

### 3. 混合 RAG 检索流程

```text
query="hybrid 个人主权系统"
  → 路由匹配 hybrid_knowledge MCP
  → HybridKnowledgeServer.execute({"op":"lookup", "query":"个人主权系统"})
  → HybridRetriever.query:
      1. 对每个 doc 调 tokenizer (CN bigram + EN word)
      2. BM25Okapi.get_scores → min-max 归一化
      3. VectorStore.search(embedded_query, k=N) → min-max 归一化
      4. fused = 0.5 * bm25_norm + 0.5 * vector_norm
      5. 排序取 top-k
  → 返回 {"hits": [{id, text, score}, ...], "top_text": ...}
```

### 4. Web 抓取 → 知识库自动入库

```text
query="fetch https://example.com/article"
  → 路由匹配 fetch_web skill
  → FetchWebToMd.execute({"op":"fetch", "url":"..."})
  → 抓取页面 → HTML 清洗 → 转 Markdown
  → 默认写入 rag/corpus/YYYYMMDD_HHMMSS_<title>.md
  → 下次 "lookup <topic>" 即可检索到新内容
  → 下次 "hybrid <topic>" 也可检索到（懒加载时重新读取 corpus）
```

### 5. 上下文恢复流程

```text
query="context"
  → 路由匹配 context skill（无 fallback）
  → ContextSkill.execute({"op":"context"})
  → LongTerm.query(subject="project") → 项目元数据
  → LongTerm.query() → 最近事实（排除 project/user/assistant）
  → ShortTerm.recent(10) → 最近 10 轮对话
  → 组装 brief: {project, recent_conversation, known_facts, summary}
  → 返回结构化简报
```

### 6. Phase 6 Reflect — 实践复盘追加

```text
query="reflect rag/corpus/foo.md --insight 新洞察 --source manual"
  → 路由匹配 reflect skill
  → ReflectSkill.execute:
      1. _resolve_path: 相对路径 / 短名 / rglob 解析到 corpus 内文件
      2. 读文件 → 解析 frontmatter revisions
      3. _is_duplicate: 24h 内同 insight 哈希 → 跳过
      4. 更新 frontmatter `revisions: [{date, insight, source_event}]`
      5. 文件末尾追加 `## 实践复盘 YYYY-MM-DD\n\n> insight: ...\n\n<insight>`
      6. 原子写：.tmp + os.replace
  → 文件 mtime 变化 → watcher 自动重跑 FTS5 + graph_index
```

### 7. Phase 5 Review — 跨时空认知审计

```text
query="review 历史 中国 朝代 --query 聚焦治理模式"
  → 路由匹配 review skill
  → ReviewSkill.execute:
      1. GraphIndex.list_paths(l1='历史', l2='中国', l3='朝代')
      2. 读每个 path 的清洗后文本，拼接成大 context（max 400k chars）
      3. 24h 缓存命中（key = domain+query hash）→ 直接返回 cached report
      4. 未命中 → _call_llm(prompt) 调 Anthropic API
      5. 缓存写入 review_cache.db（24h TTL）
  → 返回 {domain, n_docs, truncated, report, cached}
```

### 8. Phase 7 Chunks — L5 chunk 查询

```text
query="chunks rag/corpus/foo.md"
  → 路由匹配 knowledge MCP（含 chunks 前缀）
  → KnowledgeServer._do_chunks_by_path:
      1. GraphIndex(db).get_chunks(path, limit)
      2. 返回 [{chunk_id, parent_path, chunk_text, l1, l2, l3, added_at, level}]
  → 同样支持 chunks_by_cat l1 [l2] [l3] 按分类筛选
```

---

## 路由表（按优先级）

| Intent 正则 | 工具 | 类型 | fallback |
|---|---|---|---|
| `^(calc\|compute\|what is).*\d` | math_logic | skill | llm |
| `^stats.*` | math_logic | skill | llm |
| `^(context\|brief\|resume\|status\|whoami).*` | context | skill | null |
| `^(read\|load\|show\|clean\|sanitize).*file` | file_ops | skill | llm |
| `^(clean\|sanitize).*` | file_ops | skill | null |
| `^(fetch\|抓取\|下载\|crawl).*http` | fetch_web | skill | llm |
| `^find_grep\b` | pipeline_ops | skill | llm |
| `^(build\|rebuild\|update)_similarity.*(edge\|graph)?\b` | pipeline_ops | skill | llm |
| `^find\s` | find_ops | skill | llm |
| `^grep\b` | grep_ops | skill | llm |
| `^(tree\|目录树\|目录结构)\b` | tree_ops | skill | llm |
| `^(ls\|dir\|glob\|file.search\|find.files\|find files\|find file).*` | file_search | mcp | llm |
| `^(hybrid\|rag\|deep.search\|semantic).*` | hybrid_knowledge | mcp | llm |
| `^(lookup\|search\|find\|filter\|list\|tags\|chunks\|chunks_by_cat\|查询\|搜索\|查找\|寻找\|找\|帮我\|什么是\|怎么\|标签\|列出\|所有).*` | knowledge | mcp | llm |
| `^reflect\s+` | reflect | skill | llm |
| `^react\s+` | react | skill | llm |
| `^(review\|evolve)\b` | review | skill | llm |
| `.*` | claude | llm | null |

Query 归一化：`re.sub(r"\s+", " ", query.strip().lower())`。`"  Calc  2+2  "` 与 `"calc 2+2"` 路由等价。

---

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Anthropic API key（LLM 兜底必需） |
| `ANTHROPIC_MODEL` | `claude-opus-4-5-20250929` | LLM 模型 ID |
| `EMBEDDING_MODEL` | — | sentence-transformers 模型名（如 `all-MiniLM-L6-v2`）。空 / `pseudo` → 伪嵌入 |
| `CORPUS_CHUNK_ENABLED` | `1` | `1`/`true` 启用段落分块 |
| `CORPUS_CHUNK_SIZE` | `1200` | 每 chunk 最大字符数 |
| `CORPUS_CHUNK_OVERLAP` | `150` | 相邻 chunk 重叠字符数 |
| `RULES_CONFIG` | `config/rules.yaml` | 系统规则配置路径 |
| `ROUTING_CONFIG` | `config/routing.yaml` | 路由表配置路径 |
| `CACHE_PATH` | `memories/cache.db` | 语义缓存 SQLite 路径 |
| `SHORT_TERM_PATH` | `memories/short_term.json` | 短期记忆文件 |
| `LONG_TERM_DB_PATH` | `memories/long_term.db` | 长期记忆 SQLite 路径 |
| `REFLECT_DEDUP_WINDOW_HOURS` | `24` | Phase 6 — Reflect 去重窗口（小时） |
| `REVIEW_CACHE_DB` | `memories/review_cache.db` | Phase 5 — Review 缓存 DB 路径 |
| `PIPELINE_CHUNK_ENABLED` | `1` | Phase 7 — pipeline 是否写入 L5 chunks |
| `PIPELINE_CHUNK_SIZE` | `1200` | Phase 7 — pipeline chunk 大小 |
| `PIPELINE_CHUNK_OVERLAP` | `150` | Phase 7 — pipeline chunk 重叠 |
| `OLLAMA_URL` | `http://localhost:11434` | Phase 7 — Ollama API 基址 |
| `OLLAMA_MODEL` | `qwen2.5:3b` | Phase 7 — Ollama 模型名 |
| `OLLAMA_CLASSIFY_TIMEOUT` | `30` | Phase 7 — Ollama 分类超时（秒） |
| `OLLAMA_CLASSIFY_ENABLED` | `0` | Phase 7 — `1`/`true` 启用 Ollama 分类回退 |
| `URL_REGISTRY_PATH` | `memories/url_map.db` | P0-2 — fetch_web URL→path 去重注册表 DB 路径 |
| `GRAPH_DB_PATH` | `rag/graph_index.db` | P1 — `build_similarity_edges.py` 使用的 graph DB 路径 |
| `SERVER_HOST` | `127.0.0.1` | Phase 2 — HTTP API 监听地址 |
| `SERVER_PORT` | `8000` | Phase 2 — HTTP API 监听端口 |
| `SERVER_PID_FILE` | `memories/server.pid` | Phase 2 — server.py 守护进程 PID 文件 |
| `SERVER_LOG_FILE` | `memories/server.log` | Phase 2 — server.py 运行日志 |
| `REVIEW_CRON_EVERY_HOURS` | `24` | Phase 4 — Review cron 触发间隔（小时） |
| `REVIEW_CRON_POLL_SECONDS` | `60` | Phase 4 — Review cron 轮询周期（秒） |
| `REVIEW_CRON_PID_FILE` | `memories/review_cron.pid` | Phase 4 — review_cron.py PID 文件 |
| `REVIEW_CRON_LOG_FILE` | `memories/review_cron.log` | Phase 4 — review_cron.py 运行日志 |
| `REVIEWS_DIR` | `reviews` | Phase 4 — Review 报告输出目录 |

---

## 依赖

| 包 | 用途 |
|---|---|
| `pydantic>=2.6` | 配置模型校验 |
| `pyyaml>=6.0` | YAML 配置解析 |
| `numpy>=1.26` | 向量存储操作 |
| `rank-bm25>=0.2.2` | BM25 文本检索 |
| `sqlite-vec>=0.1.6` | 向量相似度搜索 |
| `mcp>=1.2.0` | MCP 协议支持 |
| `anthropic>=0.40.0` | LLM API 调用 |
| `python-dotenv>=1.0.1` | 环境变量加载 |
| `fastapi>=0.110` | Phase 2 — HTTP API 框架（`server.py`） |
| `uvicorn[standard]>=0.27` | Phase 2 — ASGI 服务器（FastAPI 运行时） |

Dev（通过 `pip install -e ".[dev]"`）：

| 包 | 用途 |
|---|---|
| `pytest>=8.0` | 测试框架 |
| `pytest-cov>=5.0` | 覆盖率报告 |
| `pytest-asyncio>=0.23` | 异步测试支持 |
| `httpx>=0.27` | Phase 2 — FastAPI TestClient transport（`test_server.py`） |

可选：

| 包 | 用途 |
|---|---|
| `sentence-transformers` | 真实语义嵌入（设置 `EMBEDDING_MODEL` 环境变量） |

---

## P0/P1 缺口补全

### P0-1 多轮对话（`agent.py`）

`_call_llm` 不再每次发送单条 user 消息，而是通过 `_build_llm_messages(query, rules)` 组装多轮 messages：

1. 取 `self._short.recent(10)`，筛选 role ∈ {`user`, `assistant`} 且 content 非空，按顺序拼成历史
2. 把当前 query 包成 `f"{rules.prompt_prefix}\n\nUser query: {query}\nOutput JSON only."`
3. 若历史末条 user 消息 content 已等于当前 query（`handle()` 已 append 过），则原地改写末条；否则 append 新 user 消息

测试：`tests/test_p0_multiturn.py`（4 用例），含用 MagicMock + monkeypatch 校验 `client.messages.create` 收到 ≥3 条 messages 且末条含 `Output JSON only`。

### P0-2 URL 去重（`memories/url_registry.py` + `skills/fetch_web_to_md.py`）

新模块 `UrlRegistry`：SQLite 表 `url_map(url PK, filepath, title, fetched_at)`，`lookup` / `record` / `count` / `clear`，线程安全。`FetchWebToMd.__init__(url_registry=None)` 接受注入；`execute()` 开头（参数校验后、`links_only` 分支前）查缓存——命中且文件仍存在则返回 `source_type="cached"`、`deduped=True` 的信封，跳过抓取。`force=True` 跳过去重。抓取成功后通过 `_record_url()` 记录（异常静默，不影响主流程）。`agent.main()` 自动注入 `UrlRegistry(os.environ.get("URL_REGISTRY_PATH", "memories/url_map.db"))`。

测试：`tests/test_p0_url_dedup.py`（7 用例）：登记/查询/upsert、fetch 命中缓存、`force=True` 绕过、抓取后登记、缓存文件丢失自动重下。

### P1 BM25 相似度边（`scripts/build_similarity_edges.py`）

离线脚本，把语料库里的文档两两算 BM25，每个文档取 top-k（默认 5）最相似的写入 `knowledge_edges`，`rel_type='bm25_similar'`，weight 为原始 BM25 分数。路径存绝对 corpus 相对路径以保证跨工具可解析。

关键点：

- **min_score 默认 -1.0**：BM25 对不相关文档会返回负分（如 `[0.96, -0.062, -0.041]`），若默认 0.0 会把 top-k 中的负分边全部滤掉。改成 -1.0 保证 top-k 结果正常落盘，用户显式传 `--min-score` 时仍可严格过滤
- **`--clear`**：先 `DELETE FROM knowledge_edges WHERE rel_type='bm25_similar'` 再重建，保证幂等
- **自环过滤**：`ranked` 生成时 `if j != i` 显式跳过自身
- 生产环境 477 文档实测生成 1485 条 `bm25_similar` 边（`knowledge_edges` 总计 1488，含原有 3 条 wikilink）

测试：`tests/test_p1_similarity_edges.py`（5 用例）：top-k 生成、单文档无自环、`--clear` 幂等、`min_score` 过滤、空语料安全返回。

#### `pipeline_ops` skill 接入（agent 可路由）

`PipelineOps` 增加 `build_similarity_edges` op,封装上述脚本,使 LLM fallback 路径也能按需触发重建。`execute(args)` 走标准信封,`corpus_dir` 和 `graph_db` 为**必填**(不读 env,避免误操作生产 graph):

```python
PipelineOps().execute({
    "op": "build_similarity_edges",
    "corpus_dir": "rag/corpus",
    "graph_db":   "rag/graph_index.db",
    "top_k": 5, "min_score": -1.0, "clear": False,
})
```

路由 `^(build|rebuild|update)_similarity.*(edge|graph)?\b` → `pipeline_ops`,例如 `build similarity edges` / `rebuild similarity graph`。

测试:`tests/test_p1_pipeline_similarity_op.py`(6 用例):基本构建、`clear` 幂等、`top_k<=0` 校验、未知 op、空 `corpus_dir`、`min_score` 非数字。

---

## 扩展指南

### 添加新 Skill

1. 在 `skills/my_skill.py` 创建实现 `execute(args: dict) -> dict` 的类
2. 在 `agent.py` 的 `main()` 中 `agent.register_skill("my_skill", MySkill())`
3. 在 `config/routing.yaml` 添加 intent → skill 路由项

### 添加新 MCP 工具

1. 在 `mcp/servers/my_server.py` 创建实现 `execute(args: dict) -> dict` 的类
2. 在 `agent.py` 的 `main()` 中 `agent.register_mcp("my_tool", MyServer())`
3. 在 `config/routing.yaml` 添加 intent → mcp 路由项

### 添加新知识源

- 把 `.txt` 或 `.md` 文件放入 `rag/corpus/`（支持子目录递归）
- 文件名带 `[tag]` 前缀可被 `filter` op 快速过滤：`[精华][职场]topic.md`
- 文件名带 `YYYYMMDD_HHMMSS_` 前缀可被日期范围过滤
- `fetch_web_to_md` 默认写入此目录，抓取后立即可被 `lookup` 检索

### 切换到真实语义嵌入

```bash
pip install sentence-transformers
# 在 .env 中设置
EMBEDDING_MODEL=all-MiniLM-L6-v2   # 384 维，快速
# 或
EMBEDDING_MODEL=all-mpnet-base-v2  # 768 维，更精确
```

`HybridKnowledgeServer` 会自动探测 embedding 维度并初始化对应 VectorStore。

---

## 相关文档

- [README.md](../ai-agent-core/README.md) — 安装与快速上手
- [operations.md](operations.md) — 完整 CLI 命令与 skill/MCP 接口手册
- [superpowers/plans/](superpowers/plans/) — 实施计划与设计决策
