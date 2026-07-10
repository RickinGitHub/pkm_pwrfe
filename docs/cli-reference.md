# AI Agent Core 命令行参考

> 所有 CLI 入口、路由映射、参数与示例的完整清单。来源：[agent.py](../ai-agent-core/agent.py) + [harness/factory.py](../ai-agent-core/harness/factory.py) + [config/routing.yaml](../ai-agent-core/config/routing.yaml) + 3 个守护进程脚本。

---

## 1. 入口总览

| 入口脚本 | 作用 | 子命令 |
|---------|------|--------|
| `python3 -m agent "<query>"` | 主入口，query 路由到 skill / MCP / LLM | （无，单次执行） |
| `python3 server.py <cmd>` | HTTP API 守护进程（FastAPI） | `run / start / stop / restart / status` |
| `python3 review_cron.py <cmd>` | Review 定时守护进程 | `run / start / stop / restart / status` |
| `python3 background_worker.py <cmd>` | 文件监控守护进程（watcher） | `run / start / stop / restart / status` |

所有守护进程共用 [harness/daemon.py](../ai-agent-core/harness/daemon.py) 的 PID / pgrep / SIGTERM 工具，模式一致：PID 文件 + pgrep 孤儿清理 + `SIGTERM`→`SIGKILL` 升级。

---

## 2. agent.py — query 路由 CLI

### 2.1 调用形式

```bash
cd ai-agent-core
python3 -m agent "<query>"           # 标准调用
python3 agent.py "<query>"            # 等价
python3 -m agent                     # 无参时默认跑 "calc 2 + 2"
```

**输出**：统一信封 JSON

```json
{"ok": true, "result": <any>, "error": null}
```

### 2.2 路由归一化

路由匹配前 query 会被归一化为 `re.sub(r"\s+", " ", query.strip().lower())`，所以 `"  Calc  2+2  "` 与 `"calc 2+2"` 路由等价。

### 2.3 路由表（来自 config/routing.yaml）

| Intent 正则 | 工具 | 类型 | 需 API key | 兜底 |
|------------|------|------|-----------|------|
| `^(calc\|compute\|what is).*\d` | math_logic | skill | 否 | llm |
| `^stats.*` | math_logic | skill | 否 | llm |
| `^(context\|brief\|resume\|status\|whoami).*` | context | skill | 否 | null |
| `^(read\|load\|show\|clean\|sanitize).*file` | file_ops | skill | 否 | llm |
| `^(clean\|sanitize).*` | file_ops | skill | 否 | null |
| `^find_grep\b` | pipeline_ops | skill | 否 | llm |
| `^(build\|rebuild\|update)_similarity.*(edge\|graph)?\b` | pipeline_ops | skill | 否 | llm |
| `^(ingest\|pipeline\|reindex)\b` | pipeline_ops | skill | 否 | llm |
| `^(unindex\|delete[ _]index\|remove[ _]index)\b` | pipeline_ops | skill | 否 | null |
| `^reload\b` | knowledge | mcp | 否 | null |
| `^find\s` | find_ops | skill | 否 | llm |
| `^grep\b` | grep_ops | skill | 否 | llm |
| `^(tree\|目录树\|目录结构)\b` | tree_ops | skill | 否 | llm |
| `^(ls\|dir\|glob\|file.search\|find.files\|find files\|find file).*` | file_search | mcp | 否 | llm |
| `^(hybrid\|rag\|deep.search\|semantic).*` | hybrid_knowledge | mcp | 否 | llm |
| `^(lookup\|search\|find\|filter\|list\|tags\|chunks\|chunks_by_cat\|查询\|搜索\|查找\|寻找\|找\|帮我\|什么是\|怎么\|标签\|列出\|所有).*` | knowledge | mcp | 否 | llm |
| `^reflect\s+` | reflect | skill | 否 | llm |
| `^react\s+` | react | skill | **是** | llm |
| `^(review\|evolve)\b` | review | skill | **是** | llm |
| `^(fetch\|抓取\|下载\|crawl).*http` | fetch_web | skill | 否 | llm |
| `.*` | claude | llm | **是** | null |

---

## 3. Skill 命令（query 子集）

### 3.1 `calc` — 算术求值

```bash
python3 -m agent "calc 2 + 3 * 4"          # → 14
python3 -m agent "calc (2 + 3) * 4"        # → 20
python3 -m agent "what is 6 * 7"           # → 42
python3 -m agent "compute 100 / 4"         # → 25.0
```

安全：`ast.parse(mode="eval")` + AST 白名单，**不是** `eval()`。

### 3.2 `stats` — 统计计算

```bash
python3 -m agent "stats 1, 2, 3, 4, 5"     # → {"mean": 3.0, "sum": 15.0, "count": 5}
```

### 3.3 `read file` — 文件读取

```bash
python3 -m agent "read file /path/to/data.txt"
python3 -m agent "load file ./config.yaml"
python3 -m agent "show file /etc/hostname"
```

### 3.4 `clean file` — 文本清洗

去每行首尾空白、丢空行（覆盖原文件）。

```bash
python3 -m agent "clean file /path/to/messy.txt"
python3 -m agent "sanitize file ./data.log"
```

### 3.5 `fetch` / `crawl` / `抓取` — 网页抓取入库

默认写入 `rag/corpus/<title>.<ext>`，立即可被 `lookup` 检索。URL 去重（P0-2 `UrlRegistry`）。

```bash
python3 -m agent "fetch https://example.com/article"
python3 -m agent "crawl https://news.ycombinator.com"
python3 -m agent "抓取 https://github.com"
python3 -m agent "fetch https://mp.weixin.qq.com/s/xxx --save-img --save-attachments"
python3 -m agent "fetch https://example.com --format json --timeout 60 --force"
```

| 选项 | 默认 | 说明 |
|------|------|------|
| `--format` | `md` | `md` / `json` / `html` |
| `--save-img` | False | 下载图片到 `<output_path>/images/` |
| `--save-attachments` | False | 下载附件到 `<output_path>/attachments/` |
| `--links-only` | False | 仅提取链接不抓正文 |
| `--timeout` | 30 | 网络超时秒 |
| `--sync` | False | 抓取后立即跑 pipeline |
| `--force` | False | 跳过 URL 去重缓存 |

### 3.6 `context` / `brief` / `resume` / `status` / `whoami` — 会话续接

从长期/短期记忆重建项目快照。新对话窗口第一句，零 Token 成本定位。

```bash
python3 -m agent "context"
python3 -m agent "whoami"
python3 -m agent "brief"
```

### 3.7 `reflect` — 实践复盘追加（Phase 6）

向老笔记追加 `## 实践复盘 YYYY-MM-DD` 段 + 更新 frontmatter `revisions`。24h 内同 insight 去重。

```bash
python3 -m agent "reflect rag/corpus/foo.md --insight 这个模式与汉代监察制度同构"
python3 -m agent "reflect foo.md --insight 新洞察 --source weekly-review"
python3 -m agent "reflect rag/corpus/foo.md"        # 无 insight → 返回 await_insight
```

### 3.8 `review` / `evolve` — 跨时空认知审计（Phase 5）

按 L1/L2/L3 分类打包全量文档调 LLM 审计，24h 缓存。

```bash
python3 -m agent "review 历史 中国 朝代"
python3 -m agent "review 科技 AI 模型 --query 聚焦模型演进"
python3 -m agent "review 科技 AI 模型 --dry-run"           # 仅打包 context 不调 LLM
python3 -m agent "review 科技 AI --max-chars 5000"
python3 -m agent "review 科技 AI 模型 --no-cache"           # 跳过缓存
```

| 选项 | 默认 | 说明 |
|------|------|------|
| 位置参数 l1/l2/l3 | — | 至少 l1 |
| `--query` | — | 聚焦 query |
| `--max-chars` | 400_000 | 文档总长上限 |
| `--dry-run` | False | 仅打包 context |
| `--no-cache` | False | 跳过 24h 缓存 |

### 3.9 `react` — ReAct 多步推理（Phase 3）

Anthropic tool-use API 驱动，LLM 自主调其他 skill/MCP 完成多跳任务。

```bash
python3 -m agent "react 先算 10/2，再 find *.md 文件"
python3 -m agent "react 分析知识库 --allowed-tools skill_math_logic mcp_knowledge"
python3 -m agent "react 深度分析 --max-steps 3"
```

| 选项 | 默认 | 说明 |
|------|------|------|
| 位置参数 query | — | 任务描述（不含 `react ` 前缀） |
| `--max-steps` | 5 | 最大推理步数，硬上限 10 |
| `--allowed-tools` | None | 白名单工具名列表 |

### 3.10 `find` — 文件查找（find_ops）

```bash
python3 -m agent "find skills -name *.py -maxdepth 1"
python3 -m agent "find . -type d -recursive -maxdepth 2"
python3 -m agent "find . -name *.log -mtime -7 -recursive"
python3 -m agent "find /var/log -size+1048576 -recursive"
python3 -m agent "find . -regex ^[A-Z].*\\.py$ -recursive"
python3 -m agent "find . -empty -recursive"
```

| 选项 | 说明 |
|------|------|
| `-name <glob>` | 文件名 glob |
| `-regex <pat>` | 文件名正则 |
| `-type f\|d` | 仅文件/仅目录 |
| `-maxdepth N` | 最大递归深度 |
| `-recursive` | 递归 |
| `-empty` | 仅空文件/目录 |
| `-size+<bytes>` | 最小文件大小 |
| `-mtime -<days>` | 最近 N 天修改 |

### 3.11 `grep` — 文本搜索（grep_ops）

```bash
python3 -m agent "grep -n \"import\" tests/ -r"
python3 -m agent "grep -iE \"def\\s+test_\\w+\" tests/ -r -n"
python3 -m agent "grep -c \"TODO\" skills/ -r"
python3 -m agent "grep -l \"pytest\" tests/ -r"
python3 -m agent "grep -v \"^#\" config/rules.yaml"
python3 -m agent "grep -rn -g *.py -C 2 \"class \" skills/"
```

| 选项 | 说明 |
|------|------|
| `-i` | 忽略大小写 |
| `-n` | 显示行号 |
| `-r` / `-R` | 递归 |
| `-l` | 仅文件名 |
| `-c` | 仅计数 |
| `-v` | 反转匹配 |
| `-E` | 正则模式 |
| `-g <glob>` | 文件名过滤 |
| `-C N` / `-A N` / `-B N` | 上下文行 |
| `-m N` | 最大匹配数 |

### 3.12 `tree` / `目录树` / `目录结构` — 目录树（tree_ops）

```bash
python3 -m agent "tree skills -L 2"
python3 -m agent "tree tests -d"
python3 -m agent "tree . -a -s -h"
python3 -m agent "tree skills -P *.py"
python3 -m agent "tree . -I *.pyc,__pycache__"
python3 -m agent "目录树 skills -L 2"
```

| 选项 | 说明 |
|------|------|
| `-L N` | 最大深度 |
| `-d` | 仅目录 |
| `-a` | 显示隐藏 |
| `-s` / `-h` | 显示大小 / 人类可读 |
| `-f` | 完整路径 |
| `-P <glob>` | 仅显示匹配 |
| `-I <glob>` | 忽略匹配 |
| `--noreport` | 不显示末尾统计 |

### 3.13 `find_grep` — 管道组合搜索（pipeline_ops）

Unix 管道风格的 `find | xargs grep`。

```bash
python3 -m agent "find_grep skills --name *.py --pattern TODO -r -n"
python3 -m agent "find_grep src --name *.py --pattern import -i -c"
python3 -m agent "find_grep . --name *.py --pattern \"^class \\w+\" -E -n -r"
python3 -m agent "find_grep . --name *.py --pattern pytest -r -l -m 5"
```

| 选项 | 说明 |
|------|------|
| `--name <glob>` / `--regex <pat>` | find 文件名 |
| `--type f\|d` | find 类型 |
| `--recursive` / `-r` | find 递归 |
| `--max-depth N` | find 最大深度 |
| `--min-size <bytes>` | find 最小大小 |
| `--mtime <days>` | find 最近 N 天修改 |
| `--pattern` / `-p` | grep 模式 |
| `-i` / `-n` / `-l` / `-c` / `-v` / `-E` | grep 标志 |
| `-A N` / `-B N` | grep 上下文 |
| `-m N` | grep 最大匹配 |

### 3.14 `build similarity edges` — BM25 相似度图（pipeline_ops，P1）

```bash
python3 -m agent "build similarity edges"
python3 -m agent "rebuild similarity graph"
python3 -m agent "update similarity edges"
```

| 选项 | 默认 | 说明 |
|------|------|------|
| `--corpus <dir>` | — | 必填，语料目录 |
| `--graph-db <path>` | — | 必填，graph DB 路径 |
| `--top-k N` | 5 | 每文档保留 k 篇相似 |
| `--min-score F` | -1.0 | BM25 最低分阈值 |
| `--clear` | False | 先清除已有 `bm25_similar` 边 |

### 3.15 `ingest` / `pipeline` / `reindex` — 手动入库（pipeline_ops）

```bash
python3 -m agent "ingest rag/corpus/foo.md"
python3 -m agent "pipeline rag/corpus/foo.md"
python3 -m agent "reindex rag/corpus/foo.md"
```

### 3.16 `unindex` / `delete index` / `remove index` — 删除索引（pipeline_ops）

```bash
python3 -m agent "unindex rag/corpus/foo.md"
python3 -m agent "delete index rag/corpus/foo.md"
```

---

## 4. MCP 命令（query 子集）

### 4.1 `reload` — 重新扫描 corpus

```bash
python3 -m agent "reload"
python3 -m agent "reload index"
python3 -m agent "rebuild index"
```

### 4.2 `lookup` / `search` / `find` / `查询` — 知识库检索（knowledge_server）

FTS5 优先 → 子串匹配 → BM25 兜底。中文前缀（查询/搜索/查找/帮我/什么是...）自动剥离。

```bash
python3 -m agent "lookup python"
python3 -m agent "search machine learning"
python3 -m agent "find 个人主权"
python3 -m agent "查询 大模型"
python3 -m agent "什么是 RAG"
```

### 4.3 `filter` — 标签过滤

交叉过滤（AND）。

```bash
python3 -m agent "filter [精华] [职场]"
python3 -m agent "filter [科技] [PAN]"
```

### 4.4 `list` / `列出` / `所有` — 文档列表

```bash
python3 -m agent "list"
python3 -m agent "list all"
python3 -m agent "列出"
python3 -m agent "所有"
```

### 4.5 `tags` / `标签` — 标签列表

```bash
python3 -m agent "tags"
python3 -m agent "show tags"
python3 -m agent "标签"
```

### 4.6 `chunks` — chunk 级检索（Phase 7）

```bash
python3 -m agent "chunks rag/corpus/foo.md"
```

### 4.7 `chunks_by_cat` — 按分类筛 chunks（Phase 7）

```bash
python3 -m agent "chunks_by_cat 科技 AI 模型"
```

### 4.8 `hybrid` / `rag` / `deep search` / `semantic` — 混合 RAG

BM25 + 向量融合检索。

```bash
python3 -m agent "hybrid python programming"
python3 -m agent "deep search knowledge graph"
python3 -m agent "rag AI agent architecture"
python3 -m agent "semantic 个人主权系统"
```

### 4.9 `ls` / `dir` / `glob` / `find files` — 文件搜索（file_search_server）

```bash
python3 -m agent "find files *.py"
python3 -m agent "ls *.md"
python3 -m agent "dir *.yaml"
python3 -m agent "glob test_*.py"
```

---

## 5. LLM 兜底

路由 `.*` 或 skill/MCP 失败且 `fallback: "llm"` 时触发。需 `ANTHROPIC_API_KEY`。

```bash
python3 -m agent "tell me a joke"
python3 -m agent "explain quantum computing"
```

无 API key 时返回（不崩溃）：

```json
{"ok": false, "result": null, "error": "ANTHROPIC_API_KEY not set"}
```

---

## 6. server.py — HTTP API 守护进程

### 6.1 子命令

```bash
cd ai-agent-core
python3 server.py run [--port 8000] [--host 127.0.0.1]   # 前台
python3 server.py start                                  # 后台启动
python3 server.py stop                                   # 停止
python3 server.py restart [--port 9000]                  # 重启
python3 server.py status                                 # 查看状态
```

### 6.2 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `SERVER_HOST` | `127.0.0.1` | 监听地址 |
| `SERVER_PORT` | `8000` | 监听端口 |
| `SERVER_PID_FILE` | `memories/server.pid` | PID 文件 |
| `SERVER_LOG_FILE` | `memories/server.log` | 日志文件 |

### 6.3 HTTP 端点

```bash
# 执行 query，返回信封
curl -s -X POST http://127.0.0.1:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "calc 2+2"}'
# {"ok": true, "result": 4, "error": null}

# 健康检查
curl -s http://127.0.0.1:8000/health
# {"ok": true}
```

线程安全：AgentCore 非线程安全，所有 `/query` 通过 `threading.Lock` 串行化。

---

## 7. review_cron.py — Review 定时守护进程

### 7.1 子命令

```bash
cd ai-agent-core
python3 review_cron.py run                         # 前台，立即跑一次 cycle
python3 review_cron.py start                       # 后台启动（默认每 24 小时）
python3 review_cron.py stop
python3 review_cron.py restart [--every-hours 12]
python3 review_cron.py status
```

### 7.2 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `REVIEW_CRON_EVERY_HOURS` | `24` | 触发间隔（小时） |
| `REVIEW_CRON_POLL_SECONDS` | `60` | 轮询周期（秒） |
| `REVIEW_CRON_PID_FILE` | `memories/review_cron.pid` | PID 文件 |
| `REVIEW_CRON_LOG_FILE` | `memories/review_cron.log` | 日志文件 |
| `REVIEWS_DIR` | `reviews` | 报告输出目录 |

### 7.3 一次 cycle 做什么

1. 调 `build_agent()` 构造 AgentCore
2. 从 `rag/graph_index.db` 查 distinct `l1`
3. 对每个 l1 调 `ReviewSkill.execute({op:"review", l1:...})`
4. 报告写到 `reviews/YYYYMMDD_HHMMSS_<l1>.md`

---

## 8. background_worker.py — 文件监控守护进程

### 8.1 子命令

```bash
cd ai-agent-core
python3 background_worker.py run [--dir rag/corpus] [--debounce-ms 500]   # 前台
python3 background_worker.py start [--dir rag/corpus]                     # 后台
python3 background_worker.py stop
python3 background_worker.py restart [--dir rag/corpus --debounce-ms 300]
python3 background_worker.py status
```

### 8.2 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `WATCHER_DIR` | `rag/corpus` | 监控目录 |
| `WATCHER_DEBOUNCE_MS` | `500` | 防抖毫秒 |
| `WATCHER_LOG_LEVEL` | `INFO` | 日志级别 |
| `WATCHER_PID_FILE` | `./.watcher.pid` | PID 文件 |
| `WATCHER_LOG_FILE` | `./.watcher.log` | 日志文件 |

### 8.3 自动 pipeline

新文件/修改文件触发：文本清洗 → 规则打 L1/L2/L3 标签 → 注入 frontmatter → upsert FTS5 → upsert `document_graph` → upsert `knowledge_edges` → upsert `document_chunks`。

---

## 9. 常见工作流

### 9.1 新对话窗口快速恢复

```bash
python3 -m agent "context"                 # 1. 项目快照 + 最近对话
python3 -m agent "tags"                    # 2. 浏览标签
python3 -m agent "filter [精华] [科技]"     # 3. 交叉过滤
python3 -m agent "lookup AI agent"         # 4. 全文检索
```

### 9.2 抓取 → 自动入库 → 检索

```bash
python3 -m agent "fetch https://example.com/article"
python3 -m agent "lookup react"            # CLI 新进程，能看到新文件
```

### 9.3 数学计算 → 缓存命中

```bash
python3 -m agent "calc 6 * 7"             # 第一次：miss → 写缓存
python3 -m agent "calc 6 * 7"             # 第二次：cache hit（<5ms）
```

### 9.4 ReAct 多步推理

```bash
python3 -m agent "react 先算 10/2，再 find *.md 文件"
python3 -m agent "react 分析知识库 --allowed-tools skill_math_logic mcp_knowledge --max-steps 3"
```

### 9.5 跨进程协同

```bash
# 终端 1：文件监控
python3 background_worker.py start

# 终端 2：HTTP API
python3 server.py start

# 终端 3：Review 定时
python3 review_cron.py start

# 终端 4：CLI 查询
python3 -m agent "lookup 大模型"
```

四个进程各自 `build_agent()` 独立实例，共享 SQLite（WAL 模式）文件，互不干扰。

---

## 10. 错误处理

所有错误通过信封返回，不抛异常：

```json
{"ok": false, "result": null, "error": "ANTHROPIC_API_KEY not set"}
{"ok": false, "result": null, "error": "no such file: /tmp/missing.txt"}
{"ok": false, "result": null, "error": "unknown tool: foo"}
{"ok": false, "result": null, "error": "no routing match"}
```

---

## 11. 参考

- [操作手册（operations.md）](operations.md) — 更详尽的参数与编程式调用示例
- [项目结构（structure.md）](structure.md) — 模块级文档
- [Telegram 机器人设计（telegram_bot_design.md）](telegram_bot_design.md) — 双工通信方案
- [Watcher Pipeline（watcher_pipeline.md）](watcher_pipeline.md) — 文件入库 pipeline 细节
- 路由配置：[ai-agent-core/config/routing.yaml](../ai-agent-core/config/routing.yaml)
- 工厂装配：[ai-agent-core/harness/factory.py](../ai-agent-core/harness/factory.py)
- 守护进程共享工具：[ai-agent-core/harness/daemon.py](../ai-agent-core/harness/daemon.py)
