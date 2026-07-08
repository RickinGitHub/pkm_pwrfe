# AI Agent Core 操作手册

> 所有可用的确定性命令与 LLM 兜底路径。适用于开发者与 LLM agent 读取后直接操作。

## Quick Start

```bash
cd ai-agent-core
pip install -e ".[dev]"           # 1. 安装依赖
cp .env.example .env              # 2. 配置 env（可选，仅 LLM 兜底需 API key）
python -m agent "calc 2 + 2"      # 3. 验证
python -m agent "context"         # 4. 新窗口快速恢复上下文
```

预期输出：
```json
{
  "ok": true,
  "result": 4,
  "error": null
}
```

## CLI 总览

**唯一入口**：`python3 -m agent "<query>"`（query 经归一化后按 `config/routing.yaml` 路由表匹配）

### 路由表

| Intent 正则 | 工具 | 类型 | 需 API key | 兜底 |
|------------|------|------|-----------|------|
| `^(calc\|compute\|what is).*\d` | math_logic | skill | 否 | llm |
| `^stats.*` | math_logic | skill | 否 | llm |
| `^(context\|brief\|resume\|status\|whoami).*` | context | skill | 否 | null |
| `^(read\|load\|show\|clean\|sanitize).*file` | file_ops | skill | 否 | llm |
| `^(clean\|sanitize).*` | file_ops | skill | 否 | null |
| `^find_grep\b` | pipeline_ops | skill | 否 | llm |
| `^(build\|rebuild\|update)_similarity.*(edge\|graph)?\b` | pipeline_ops | skill | 否 | llm |
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

### Query 归一化

路由匹配前，query 会被归一化：`re.sub(r"\s+", " ", query.strip().lower())`。所以 `"  Calc  2+2  "` 与 `"calc 2+2"` 路由等价。

---

## Skill 命令（确定性，无 LLM）

所有 skill 遵循 `execute(args: dict) -> dict` 协议，返回信封 `{"ok": bool, "result": Any, "error": str | None}`。

### 1. `calc` — 算术求值（math_logic）

**CLI**：
```bash
python3 -m agent "calc 2 + 3 * 4"          # → 14
python3 -m agent "calc (2 + 3) * 4"        # → 20
python3 -m agent "what is 6 * 7"           # → 42
python3 -m agent "compute 100 / 4"         # → 25.0
```

**编程式**：
```python
from skills.math_logic import MathLogic
out = MathLogic().execute({"op": "calc", "expr": "2 + 3 * 4"})
# {"ok": True, "result": 14, "error": None}
```

**参数**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `op` | str | 是 | `"calc"` |
| `expr` | str | 是 | 算术表达式，支持 `+ - * / // % **` 和括号、整数/浮点数 |

**安全**：使用 `ast.parse(mode="eval")` + AST 白名单，拒绝 `__import__`、`Call`、`Attribute` 等节点。**不是** `eval()`。

### 2. `stats` — 统计计算（math_logic）

**CLI**：
```bash
python3 -m agent "stats 1, 2, 3, 4, 5"       # → {"mean": 3.0, "sum": 15.0, "count": 5}
python3 -m agent "stats 10, 20, 30"           # → {"mean": 20.0, "sum": 60.0, "count": 3}
```

**编程式**：
```python
out = MathLogic().execute({"op": "stats", "values": [1, 2, 3, 4]})
# {"ok": True, "result": {"mean": 2.5, "sum": 10.0, "count": 4}, "error": None}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `op` | str | 是 | `"stats"` |
| `values` | list[number] | 是 | 非空数字列表 |

### 3. `read file` — 文件读取（file_ops）

**CLI**：
```bash
python3 -m agent "read file /path/to/data.txt"
python3 -m agent "load file ./config.yaml"
python3 -m agent "show file /etc/hostname"
```

**编程式**：
```python
from skills.file_ops import FileOps
out = FileOps().execute({"op": "read", "path": "/path/to/data.txt"})
# {"ok": True, "result": "file content...", "error": None}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `op` | str | 是 | `"read"` |
| `path` | str | 是 | 文件路径 |

### 4. `clean file` — 文本清洗（file_ops）

去除每行首尾空白、丢弃空行。

**CLI**：
```bash
python3 -m agent "clean file /path/to/messy.txt"
python3 -m agent "sanitize file ./data.log"
```

**编程式**：
```python
out = FileOps().execute({"op": "clean", "path": "/path/to/messy.txt"})
# 输入 "  foo  \n\nbar\n   \nbaz" → 输出 "foo\nbar\nbaz"
```

### 5. `fetch url` — 网页抓取转 Markdown（fetch_web_to_md）

**默认输出到 `rag/corpus/`**：抓取的 `.md`/`.json`/`.html` 直接落入知识库，立即可被 `lookup` 检索。文件名基于原文 title 自动生成（`<title>.<ext>`，无时间戳前缀）。可通过 `output_path` 指定输出**目录**（相对或绝对路径）覆盖。

**URL 去重（P0-2）**：`FetchWebToMd` 接受可选的 `UrlRegistry`（SQLite），缓存 URL→filepath 映射。重复 `fetch` 同一 URL 直接返回缓存路径（`source_type="cached"`，`deduped=true`），不重新下载。`force=True` 绕过缓存；缓存文件不存在时自动回退为重新下载。`build_agent()` 工厂已自动注入 `UrlRegistry`。

**CLI**：
```bash
python3 -m agent "fetch https://example.com/article"
python3 -m agent "fetch https://mp.weixin.qq.com/s/xxx"
python3 -m agent "crawl https://news.ycombinator.com"
python3 -m agent "抓取 https://github.com"
```

**编程式**（完整参数）：
```python
from skills.fetch_web_to_md import FetchWebToMd
from memories.url_registry import UrlRegistry

url_registry = UrlRegistry("memories/url_map.db")  # P0-2: URL 去重
out = FetchWebToMd(url_registry=url_registry).execute({
    "op": "fetch",
    "url": "https://mp.weixin.qq.com/s/xxx",
    "format": "md",              # 可选: md / json / html（默认 md）
    "save_img": False,           # 可选: 下载图片到 <output_path>/images/ 并改写 .md URL
    "save_attachments": False,   # 可选: 下载附件 (pdf/zip/docx/mp4/...) 到 <output_path>/attachments/ 并改写 .md URL
    "output_path": None,         # 可选: 输出**目录**（相对或绝对），默认 rag/corpus/
    "timeout": 30,               # 可选: 网络超时秒
    "links_only": False,         # 可选: 仅提取链接不抓正文
    "force": False,              # 可选: True 跳过 URL 去重缓存，强制重新下载
})
```

**返回**：
```python
{
    "ok": True,
    "result": {
        "filepath": "rag/corpus/Test Article.md",
        "title": "Test Article",
        "author": "...",
        "chars": 1234,
        "links_count": 5,
        "images_count": 2,
        "attachments_count": 0,
        "images_downloaded": 0,
        "attachments_downloaded": 0,
        "format": "md",
        "source_type": "wechat",  # 或 "web" 或 "cached"（URL 去重命中）
        "deduped": false          # true = URL 去重命中，返回缓存路径
    },
    "error": None
}
```

**参数**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `op` | str | 是 | — | `"fetch"` |
| `url` | str | 是 | — | 必须以 `http://` 或 `https://` 开头 |
| `format` | str | 否 | `"md"` | `md` / `json` / `html` |
| `save_img` | bool | 否 | False | 下载图片到 `<output_path>/images/`，并把 .md 里的图片 URL 改写为本地相对路径 |
| `save_attachments` | bool | 否 | False | 下载文件附件（pdf/zip/docx/xlsx/pptx/mp4/mp3/...）到 `<output_path>/attachments/`，并改写 .md URL |
| `output_path` | str | 否 | None | 输出**目录**（相对或绝对路径）。None 时用默认 `rag/corpus/`。文件名基于 title：`<title>.<ext>` |
| `timeout` | int | 否 | 30 | 必须 > 0 |
| `links_only` | bool | 否 | False | 仅返回链接列表，不抓正文 |
| `force` | bool | 否 | False | 跳过 URL 去重缓存，强制重新下载（P0-2） |

**支持的源**：微信公众号（`weixin.qq.com`，自动用微信 UA）、任意网页（通用 UA）。

**嵌入媒体处理**：`<iframe>` / `<video>` / `<audio>` / `<source>` / `<embed>` 标签统一转为可点击 Markdown 链接占位（`[📎 Video](url)` 等），原 URL 完整保留，CDN 失效后仍可点击访问原文。

**自动入库**：默认 `output_path=None` 时文件写入 `rag/corpus/`。需调用 `KnowledgeServer.reload()` 或重启进程才能识别新文件。CLI 每次都是新进程，所以下一条 `lookup` 能看到新文件。URL 去重命中时返回缓存路径，不重新写入。

### 6. `context` — 会话续接（context skill）

从长期记忆和短期记忆中重建项目上下文。**新对话窗口第一句命令，零 Token 成本快速定位。**

**CLI**：
```bash
python -m agent "context"          # 完整项目快照
python -m agent "whoami"           # 同上（别名）
python -m agent "brief"            # 同上（别名）
python -m agent "status"           # 同上（别名）
python -m agent "resume"           # 同上（别名）
```

**返回**：
```json
{
  "project": {
    "name": "ai-agent-core",
    "version": "0.1.0",
    "architecture": "cache → skills → MCP → LLM fallback",
    "last_boot": "2026-07-07T04:26:35",
    "skills": "math_logic, file_ops, fetch_web, context"
  },
  "recent_conversation": [
    {"role": "user", "content": "calc 1+1", "ts": "..."}
  ],
  "summary": "# ai-agent-core v0.1.0\n  最后启动: ...\n  ..."
}
```

**工作原理**：
1. 首次启动时 `bootstrap_memory()` 将项目元数据写入长期记忆（幂等）
2. 每次 `handle()` 调用自动记录到短期记忆（最近 50 轮）
3. `context` 命令读取两者，输出结构化快照

**编程式**：
```python
from skills.context import ContextSkill
out = ContextSkill().execute({"op": "context"})
```

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `op` | str | 是 | — | `"context"` |
| `recent_n` | int | 否 | 10 | 最近对话轮数 |
| `long_term_path` | str | 否 | env `LONG_TERM_DB_PATH` | 长期记忆路径 |
| `short_term_path` | str | 否 | env `SHORT_TERM_PATH` | 短期记忆路径 |

### 7. `reflect` — 实践复盘追加（Phase 6）

向老笔记追加 `## 实践复盘 YYYY-MM-DD` 段，同时更新 frontmatter `revisions` 数组。24h 内同 insight 文本去重（`REFLECT_DEDUP_WINDOW_HOURS` 可配置）。原子写入：`.tmp + os.replace`。

**CLI**：
```bash
# 标准用法
python3 -m agent "reflect rag/corpus/foo.md --insight 这个模式与汉代监察制度同构"

# 带来源标记
python3 -m agent "reflect rag/corpus/foo.md --insight 决策应分离 collect 与 decide --source weekly-review"

# 短名（自动解析到 rag/corpus/<name>）
python3 -m agent "reflect foo.md --insight 新洞察"

# 仅传 path 不传 insight → 返回 action=await_insight（提示用户提供洞察）
python3 -m agent "reflect rag/corpus/foo.md"
```

**编程式**：
```python
from skills.reflect import ReflectSkill
out = ReflectSkill().execute({
    "op": "reflect",
    "raw_query": 'reflect rag/corpus/foo.md --insight "新洞察" --source manual',
})
# {"ok": True, "result": {"action": "appended", "path": "...", "date": "2026-07-07",
#                         "revision_index": 0, "total_revisions": 1, "note": "..."}, "error": None}
```

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `op` | str | 是 | — | `"reflect"` |
| `raw_query` | str | 是 | — | 完整命令字符串，由 `_CMD_RE` 解析 |
| `path` | str | 否 | — | 直接传 path（绕过 raw_query 解析） |
| `insight` | str | 否 | — | 实践洞察文本 |
| `source_event` | str | 否 | — | 来源标记（如 `manual`、`weekly-review`） |

**路径解析**：相对路径 → cwd；短名（`foo.md`）→ `rag/corpus/foo.md`；否则 rglob 整个 corpus。

**幂等性**：24h 内同 `insight` 哈希命中 → `action=skipped`，不重复写入。

### 8. `review` / `evolve` — 跨时空认知审计（Phase 5）

按 L1/L2/L3 分类批量打包全量文档，调 LLM 做认知审计。与 `lookup` 互补：lookup 毫秒级返回 snippet，review 秒级烧 token 适合周末静思。

**CLI**：
```bash
# 标准用法（24h 缓存，同 domain+query 复用）
python3 -m agent "review 历史 中国 朝代"

# 带聚焦 query
python3 -m agent "review 科技 AI 模型 --query 聚焦模型演进"

# 仅打包 context 不调 LLM（debug 用）
python3 -m agent "review 科技 AI 模型 --dry-run"

# 限制 token 预算
python3 -m agent "review 科技 AI --max-chars 5000"

# 跳过缓存（强制重算）
python3 -m agent "review 科技 AI 模型 --no-cache"
```

**编程式**：
```python
from skills.review import ReviewSkill
out = ReviewSkill().execute({
    "op": "review",
    "l1": "历史", "l2": "中国", "l3": "朝代",
    "query": "聚焦治理模式",
    "max_chars": 400_000,   # 默认 ~100k tokens
    "use_cache": True,
    "dry_run": False,
    "graph_db_path": "rag/graph_index.db",   # 可选，默认 _DEFAULT_GRAPH_DB
    "cache_db_path": "memories/review_cache.db",  # 可选，默认 REVIEW_CACHE_DB env
})
# {"ok": True, "result": {"domain": {...}, "n_docs": 12, "truncated": False,
#                         "chars": 85000, "report": "# 审计报告\n...", "cached": False}, "error": None}
```

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `op` | str | 是 | — | `"review"` 或 `"evolve"`（同义） |
| `l1` | str | 是 | — | 一级分类（至少 l1/l2/l3 之一） |
| `l2` | str | 否 | — | 二级分类 |
| `l3` | str | 否 | — | 三级分类 |
| `query` | str | 否 | — | 聚焦 query，注入到 prompt 头部 |
| `max_chars` | int | 否 | 400_000 | 文档总长上限（~100k tokens） |
| `use_cache` | bool | 否 | True | 是否读写 24h 缓存 |
| `dry_run` | bool | 否 | False | 仅打包 context，不调 LLM |
| `graph_db_path` | str | 否 | env `GRAPH_DB_PATH` / 默认 `rag/graph_index.db` | graph DB 路径 |
| `cache_db_path` | str | 否 | env `REVIEW_CACHE_DB` / 默认 `memories/review_cache.db` | 缓存 DB 路径 |

**返回字段**：`{domain: {l1,l2,l3}, n_docs, truncated, chars, context (dry_run), report, cached}`

### 9. `react` — ReAct 多步推理

基于 Anthropic tool-use API 的 ReAct 循环。LLM 作为规划器，自主调用其他 skill / MCP 工具完成多跳任务。工具名 `skill_<name>` / `mcp_<name>`，结果 JSON 截断到 2000 字符后回灌给 LLM，`stop_reason=="end_turn"` 或 `max_steps` 触发停止。

**CLI**：
```bash
# 多跳任务：算数 + 文件查找
python3 -m agent "react 先算 10/2，再 find *.md 文件"

# 限制工具集（避免 LLM 误用危险工具）
python3 -m agent "react 分析知识库 --allowed-tools skill_math_logic mcp_knowledge"

# 限制步数
python3 -m agent "react 深度分析 --max-steps 3"
```

**编程式**：
```python
from skills.react import ReactSkill
# ReactSkill 需要 agent 引用，通常由 build_agent() 自动注册
# 手动构造：
from harness.factory import build_agent
agent = build_agent()
# factory 已注册 react skill，直接调用：
out = agent.handle('react 先算 10/2，再 find *.md 文件')
# 或直接调 skill：
# react = agent._skills["react"]
# out = react.execute({"query": "先算 10/2", "max_steps": 5, "allowed_tools": None})
```

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `query` | str | 是 | — | 任务描述（不含 `react ` 前缀） |
| `max_steps` | int | 否 | 5 | 最大推理步数，硬上限 10 |
| `allowed_tools` | list[str] \| None | 否 | None | 白名单工具名；None 表示全部可用 |

**返回**：
```python
{
    "ok": True,
    "result": {
        "answer": "最终回答文本...",
        "steps": 3,
        "tool_calls": [
            {"tool": "skill_math_logic", "input": {"expr": "10/2"}, "output": "5.0"},
            {"tool": "skill_find_ops", "input": {...}, "output": "..."},
        ],
    },
    "error": None,
}
```

**安全**：硬上限 `_MAX_STEPS_HARD_CAP=10`；缺 `ANTHROPIC_API_KEY` → `err("ANTHROPIC_API_KEY not set")`；工具结果超 2000 字符自动截断。

### 10. `find` — 文件查找（find_ops）

Linux `find` 风格的文件搜索 skill。按名称 glob、正则、类型、大小、修改时间等条件查找文件/目录。

**CLI**：
```bash
# 按文件名 glob 查找
python3 -m agent "find skills -name *.py -maxdepth 1"

# 递归查找所有目录
python3 -m agent "find . -type d -recursive -maxdepth 2"

# 按修改时间查找（最近 7 天）
python3 -m agent "find . -name *.log -mtime -7 -recursive"

# 按最小大小查找（字节）
python3 -m agent "find /var/log -size+1048576 -recursive"

# 正则匹配文件名
python3 -m agent "find . -regex ^[A-Z].*\\.py$ -recursive"

# 查找空文件
python3 -m agent "find . -empty -recursive"
```

**编程式**：
```python
from skills.find_ops import FindOps
out = FindOps().execute({
    "op": "find", "path": "skills", "name": "*.py",
    "max_depth": 1, "recursive": True,
})
# {"ok": True, "result": [{"path": "skills/math_logic.py", "name": "math_logic.py",
#                          "size": 1234, "modified": "2026-07-07T..."}], "error": None}
```

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `op` | str | 是 | — | `"find"` |
| `path` | str | 否 | `"."` | 搜索起始目录 |
| `name` | str | 否 | — | 文件名 glob 模式（如 `*.py`） |
| `regex` | str | 否 | — | 文件名正则模式 |
| `type` | str | 否 | — | `"f"` 仅文件 / `"d"` 仅目录 |
| `max_depth` | int | 否 | — | 最大递归深度 |
| `recursive` | bool | 否 | False | 是否递归 |
| `empty` | bool | 否 | False | 仅查找空文件/目录 |
| `min_size` | int | 否 | — | 最小文件大小（字节） |
| `modified_within_days` | int | 否 | — | 最近 N 天内修改 |

### 11. `grep` — 文本搜索（grep_ops）

Linux `grep` 风格的文本搜索 skill。在文件或目录中按正则/子串搜索匹配行。

**CLI**：
```bash
# 递归搜索
python3 -m agent "grep -n \"import\" tests/ -r"

# 忽略大小写 + 上下文行
python3 -m agent "grep -iE \"def\\s+test_\\w+\" tests/ -r -n"

# 仅计数
python3 -m agent "grep -c \"TODO\" skills/ -r"

# 仅文件名
python3 -m agent "grep -l \"pytest\" tests/ -r"

# 反转匹配
python3 -m agent "grep -v \"^#\" config/rules.yaml"

# glob 过滤 + 上下文
python3 -m agent "grep -rn -g *.py -C 2 \"class \" skills/"
```

**编程式**：
```python
from skills.grep_ops import GrepOps
out = GrepOps().execute({
    "op": "search", "pattern": "TODO", "path": "skills",
    "glob": "*.py", "recursive": True, "line_number": True,
})
# {"ok": True, "result": [{"path": "skills/find_ops.py", "line": 10,
#                          "content": "# TODO: ...", "line_no": 10}], "error": None}
```

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `op` | str | 是 | — | `"search"` |
| `pattern` | str | 是 | — | 搜索模式（正则或子串） |
| `path` | str | 否 | `"."` | 搜索路径（文件或目录） |
| `glob` | str | 否 | — | 文件名 glob 过滤（如 `*.py`） |
| `recursive` | bool | 否 | False | 递归搜索目录 |
| `ignore_case` | bool | 否 | False | 忽略大小写 |
| `line_number` | bool | 否 | False | 显示行号 |
| `invert` | bool | 否 | False | 反转匹配（显示不匹配的行） |
| `use_regex` | bool | 否 | False | 启用正则模式 |
| `count` | bool | 否 | False | 仅返回匹配计数 |
| `files_with_matches` | bool | 否 | False | 仅返回匹配文件名 |
| `context_before` | int | 否 | — | 匹配行前 N 行上下文 |
| `context_after` | int | 否 | — | 匹配行后 N 行上下文 |
| `max_count` | int | 否 | — | 最大匹配数 |

### 12. `tree` — 目录树（tree_ops）

Linux `tree` 风格的目录树展示 skill。

**CLI**：
```bash
# 基础树形展示
python3 -m agent "tree skills -L 2"

# 只显示目录
python3 -m agent "tree tests -d"

# 显示隐藏文件 + 大小
python3 -m agent "tree . -a -s -h"

# 按 glob 过滤
python3 -m agent "tree skills -P *.py"

# 忽略某些文件
python3 -m agent "tree . -I *.pyc,__pycache__"

# 中文别名
python3 -m agent "目录树 skills -L 2"
python3 -m agent "目录结构 ."
```

**编程式**：
```python
from skills.tree_ops import TreeOps
out = TreeOps().execute({"op": "tree", "path": "skills", "max_depth": 2})
# {"ok": True, "result": "skills\n├── math_logic.py\n├── file_ops.py\n...", "error": None}
```

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `op` | str | 是 | — | `"tree"` |
| `path` | str | 否 | `"."` | 起始目录 |
| `max_depth` | int | 否 | — | 最大递归深度 |
| `dirs_only` | bool | 否 | False | 仅显示目录 |
| `all_files` | bool | 否 | False | 显示隐藏文件 |
| `show_size` | bool | 否 | False | 显示文件大小 |
| `human_size` | bool | 否 | False | 人类可读大小（需 `show_size=True`） |
| `full_path` | bool | 否 | False | 显示完整路径前缀 |
| `pattern` | str | 否 | — | 仅显示匹配 glob 的文件 |
| `ignore` | str | 否 | — | 忽略匹配 glob 的文件（逗号分隔多个） |
| `noreport` | bool | 否 | False | 不显示末尾统计摘要 |

### 13. `find_grep` — 管道组合搜索（pipeline_ops）

Unix 管道风格的 `find | xargs grep` 组合器。先按条件查找文件，再在匹配文件中搜索文本。

**CLI**：
```bash
# find + grep: 查找所有 .py 文件，在其中搜索 "TODO"
python3 -m agent "find_grep skills --name *.py --pattern TODO -r -n"

# 忽略大小写 + 仅计数
python3 -m agent "find_grep src --name *.py --pattern import -i -c"

# 正则 + 上下文行
python3 -m agent "find_grep . --name *.py --pattern \"^class \\w+\" -E -n -r"

# 仅列出匹配的文件名
python3 -m agent "find_grep . --name *.py --pattern pytest -r -l -m 5"
```

**编程式**：
```python
from skills.pipeline_ops import PipelineOps
out = PipelineOps().execute({
    "op": "find_grep", "path": "skills",
    "find_name": "*.py", "find_recursive": True,
    "grep_pattern": "TODO", "grep_line_number": True,
})
# {"ok": True, "result": [{"path": "...", "line": 10, "content": "..."}], "error": None}
```

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `op` | str | 是 | — | `"find_grep"` |
| `path` | str | 否 | `"."` | 搜索起始目录 |
| `find_name` | str | 否 | — | find 的文件名 glob |
| `find_regex` | str | 否 | — | find 的文件名正则 |
| `find_type` | str | 否 | — | find 的类型过滤 `f`/`d` |
| `find_recursive` | bool | 否 | False | find 是否递归 |
| `find_max_depth` | int | 否 | — | find 最大深度 |
| `find_min_size` | int | 否 | — | find 最小文件大小 |
| `find_modified_within_days` | int | 否 | — | find 最近 N 天修改 |
| `grep_pattern` | str | 是 | — | grep 搜索模式 |
| `grep_ignore_case` | bool | 否 | False | grep 忽略大小写 |
| `grep_line_number` | bool | 否 | False | grep 显示行号 |
| `grep_invert` | bool | 否 | False | grep 反转匹配 |
| `grep_use_regex` | bool | 否 | False | grep 正则模式 |
| `grep_count` | bool | 否 | False | grep 仅计数 |
| `grep_files_with_matches` | bool | 否 | False | grep 仅文件名 |
| `grep_context_before` | int | 否 | — | grep 前文行数 |
| `grep_context_after` | int | 否 | — | grep 后文行数 |
| `grep_max_count` | int | 否 | — | grep 最大匹配数 |

### 14. `build_similarity_edges` — BM25 相似度图构建（pipeline_ops, P1）

为 `rag/corpus/` 中每个文档计算 BM25 相似度，将 top-k 最相似文档写入 `knowledge_edges` 表（`rel_type='bm25_similar'`）。幂等：按 `source_path + target_path` upsert。

**CLI**：
```bash
python3 -m agent "build similarity edges"
python3 -m agent "rebuild similarity graph"
python3 -m agent "update similarity edges"
```

**编程式**：
```python
from skills.pipeline_ops import PipelineOps
out = PipelineOps().execute({
    "op": "build_similarity_edges",
    "corpus_dir": "rag/corpus",       # 必填
    "graph_db": "rag/graph_index.db",  # 必填
    "top_k": 5,         # 默认 5
    "min_score": -1.0,  # 默认 -1.0（0.0 会过滤掉 BM25 负分文档）
    "clear": False,     # True = 先清除已有 bm25_similar 边
})
# {"ok": True, "result": {"docs": 477, "edges_added": 1485, ...}, "error": None}
```

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `op` | str | 是 | — | `"build_similarity_edges"` |
| `corpus_dir` | str | 是 | — | 语料目录（如 `rag/corpus`） |
| `graph_db` | str | 是 | — | graph DB 路径（如 `rag/graph_index.db`） |
| `top_k` | int | 否 | 5 | 每个文档保留最相似的 k 篇 |
| `min_score` | float | 否 | -1.0 | BM25 最低分数阈值 |
| `clear` | bool | 否 | False | 是否先清除已有 `bm25_similar` 边 |

> **注意**：`corpus_dir` 和 `graph_db` 无环境变量回退（防止误操作生产图库）。

---

## MCP 命令

### `lookup` / `filter` / `list` / `tags` / `chunks` / `chunks_by_cat` — 知识库操作（knowledge_server）

知识库支持六种操作，统一路由到 `knowledge_server`：

**CLI**：
```bash
# 文本检索（FTS5 优先 → 子串匹配 → BM25 兜底）
python -m agent "lookup python"
python -m agent "search machine learning"
python -m agent "find 个人主权"

# 标签过滤（交叉过滤，AND 逻辑）
python -m agent "filter [精华] [职场]"
python -m agent "filter [科技] [PAN]"

# 文档列表（含标题/日期/标签/来源）
python -m agent "list"
python -m agent "list all"

# 标签列表（全部 36 个标签）
python -m agent "tags"
python -m agent "show tags"

# Phase 7: chunk 级检索
python -m agent "chunks rag/corpus/foo.md"           # 返回某文档的所有 L5 chunks
python -m agent "chunks_by_cat 科技 AI 模型"          # 按分类筛选 chunks
```

**编程式**：
```python
from mcp.servers.knowledge_server import KnowledgeServer
from rag.metadata import MetadataIndex

meta = MetadataIndex("rag/corpus")
meta.build()
srv = KnowledgeServer("rag/corpus", metadata=meta)

# lookup
srv.execute({"op": "lookup", "query": "python"})
# → {"ok": True, "result": "Python is a programming language..."}

# filter
srv.execute({"op": "filter", "tags": ["精华", "职场"]})
# → {"ok": True, "result": {"count": 1, "docs": [{...}]}}

# list
srv.execute({"op": "list"})
# → {"ok": True, "result": {"count": 249, "docs": [{...}]}}

# tags
srv.execute({"op": "tags"})
# → {"ok": True, "result": {"count": 36, "tags": [...]}}
```

**各操作参数**：

| 操作 | op | 参数 | 类型 | 必填 | 说明 |
|------|----|------|------|------|------|
| lookup | `"lookup"` | `query` | str | 是 | 检索关键词 |
| | | `tags` | list[str] | 否 | 预过滤标签（AND 交叉） |
| filter | `"filter"` | `tags` | list[str] | 是 | 标签列表（AND 交叉过滤） |
| | | `date_from` | str | 否 | 起始日期 `YYYYMMDD` |
| | | `date_to` | str | 否 | 截止日期 |
| | | `max_results` | int | 否 | 默认 50 |
| list | `"list"` | — | — | — | 无参数，返回全部文档元数据 |
| tags | `"tags"` | — | — | — | 无参数，返回全部标签 |
| chunks | `"chunks"` | `path` | str | 是 | 文档路径（如 `rag/corpus/foo.md`） |
| | | `limit` | int | 否 | 默认 1000 |
| chunks_by_cat | `"chunks_by_cat"` | `l1` | str | 是 | 一级分类 |
| | | `l2` | str | 否 | 二级分类 |
| | | `l3` | str | 否 | 三级分类 |
| | | `limit` | int | 否 | 默认 1000 |

**文档元数据格式**（filter/list 返回）：
```json
{
  "id": "records/[精华][职场]xxx.md",
  "title": "个人主权系统迭代与实战应用",
  "tags": ["精华", "职场", "沟通"],
  "date": "20260618",
  "source_url": "https://...",
  "chars": 28500
}
```

**标签来源**：从文件名中的 `[标签]` 自动提取，如 `[精华][科技]xxx.md` → tags: `["精华", "科技"]`。

**注意**：
- `lookup` 在**完整文档**中搜索（不受 chunk 影响），返回完整文档文本或 FTS5 snippet
- `filter` 是纯元数据过滤，速度极快（O(1) 标签查找）
- `list` 返回所有文档的标题/标签/日期/来源，适合"浏览知识库"场景
- `chunks` / `chunks_by_cat` 返回 L5 chunk 级文本，适合需要细粒度上下文的场景（如 RAG 精确引用）。需要 `KnowledgeServer` 注入 `graph_db_path` 参数，agent.py `main()` 已自动配置

### `hybrid` — 混合 RAG 检索（hybrid_knowledge_server）

BM25 + 向量融合检索，语义理解更强。加载 `rag/corpus/` 递归所有文件，伪嵌入（确定性 SHA256 哈希）兜底。

**CLI**：
```bash
python3 -m agent "hybrid python programming"
python3 -m agent "deep search knowledge graph"
python3 -m agent "rag AI agent architecture"
python3 -m agent "semantic 个人主权系统"
```

**编程式**：
```python
from mcp.servers.hybrid_knowledge_server import HybridKnowledgeServer
srv = HybridKnowledgeServer("rag/corpus")
out = srv.execute({"op": "lookup", "query": "python", "k": 5})
# {"ok": True, "result": {"hits": [...], "top_text": "..."}, "error": None}
```

**参数**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `op` | str | 是 | — | `"lookup"` |
| `query` | str | 是 | — | 检索词（非空） |
| `k` | int | 否 | 5 | 返回结果数量 |

### `find files` — 文件搜索（file_search_server）

递归搜索项目中匹配 glob 模式的文件。

**CLI**：
```bash
python3 -m agent "find files *.py"
python3 -m agent "ls *.md"
python3 -m agent "dir *.yaml"
python3 -m agent "glob test_*.py"
```

**编程式**：
```python
from mcp.servers.file_search_server import FileSearchServer
srv = FileSearchServer(".")
out = srv.execute({"op": "search", "pattern": "*.py", "max_results": 10})
# {"ok": True, "result": {"pattern": "*.py", "count": 10, "files": [...]}, "error": None}
```

**参数**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `op` | str | 是 | — | `"search"` |
| `pattern` | str | 是 | — | Glob 模式（如 `*.py`、`test_*`） |
| `dir` | str | 否 | `"."` | 搜索起始目录 |
| `max_results` | int | 否 | 20 | 最大返回数量 |
| `case_sensitive` | bool | 否 | false | 大小写敏感 |

---

## LLM 兜底

### 触发条件

任一以下情况触发 LLM 路径：

1. 路由匹配 `.*`（无 skill / mcp 命中）
2. skill / mcp 返回 `ok=False` 且该路由条目 `fallback: "llm"`

### 环境变量

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-xxxxx             # 必填（仅 LLM 兜底 / Review / React skill 需要）
ANTHROPIC_MODEL=claude-opus-4-5-20250929   # 可选，默认即此值

# Embedding（可选，不设置则用确定性伪嵌入）
EMBEDDING_MODEL=                           # 留空 = pseudo；设为 all-MiniLM-L6-v2 启用语义嵌入

# Chunking（可选，默认开启）
CORPUS_CHUNK_ENABLED=1                     # 1=开启 0=关闭
CORPUS_CHUNK_SIZE=1200                     # 每块最大字符数
CORPUS_CHUNK_OVERLAP=150                   # 块间重叠字符数

# 路径配置（可选，均有默认值）
RULES_CONFIG=config/rules.yaml             # 系统规则配置
ROUTING_CONFIG=config/routing.yaml         # 路由表配置
CACHE_PATH=memories/cache.db               # 语义缓存 DB
SHORT_TERM_PATH=memories/short_term.json   # 短期记忆文件
LONG_TERM_DB_PATH=memories/long_term.db    # 长期记忆 DB
FTS_INDEX_PATH=rag/fts_index.db            # FTS5 索引 DB
TAG_RULES_CONFIG=config/tag_rules.yaml     # 标签分类规则
INDEX_YAML_PATH=config/index.yaml          # 只读 YAML 快照路径
GRAPH_DB_PATH=rag/graph_index.db           # 图索引 DB（P1 similarity edges 用）
URL_REGISTRY_PATH=memories/url_map.db      # URL→path 去重注册表（P0-2）

# Watcher Pipeline
WATCHER_DIR=rag/corpus                     # 监控目录
WATCHER_DEBOUNCE_MS=500                    # 事件防抖毫秒
WATCHER_LOG_LEVEL=INFO                     # 日志级别

# Phase 5 — Review skill
REVIEW_CACHE_DB=memories/review_cache.db   # Review 缓存 DB

# Phase 6 — Reflect skill
REFLECT_DEDUP_WINDOW_HOURS=24              # 24h 内同 insight 去重

# Phase 7 — Pipeline chunk-level L5 index
PIPELINE_CHUNK_ENABLED=1                   # 1=写入 document_chunks 表
PIPELINE_CHUNK_SIZE=1200
PIPELINE_CHUNK_OVERLAP=150

# Phase 7 — Offline Ollama classifier（默认禁用）
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:3b
OLLAMA_CLASSIFY_TIMEOUT=30
OLLAMA_CLASSIFY_ENABLED=0                  # 1=启用 rules → Ollama 回退

# HTTP API server
SERVER_HOST=127.0.0.1
SERVER_PORT=8000
SERVER_PID_FILE=memories/server.pid
SERVER_LOG_FILE=memories/server.log

# Review cron daemon
REVIEW_CRON_EVERY_HOURS=24
REVIEW_CRON_POLL_SECONDS=60
REVIEW_CRON_PID_FILE=memories/review_cron.pid
REVIEW_CRON_LOG_FILE=memories/review_cron.log
REVIEWS_DIR=reviews
```

### CLI 示例

```bash
python3 -m agent "tell me a joke"
python3 -m agent "explain quantum computing"
```

无 API key 时返回明确错误（不会崩溃）：
```json
{
  "ok": false,
  "result": null,
  "error": "ANTHROPIC_API_KEY not set"
}
```

### Prompt 构造

```
{rules.prompt_prefix}

User query: {query}
Output JSON only.
```

`rules.yaml` 的 `prompt_prefix` 默认强制 LLM 输出 JSON：`{"ok": true, "result": <any>, "error": null}`。

---

## 典型工作流

### 新对话窗口快速恢复

```bash
python -m agent "context"                 # 1. 项目快照 + 最近对话
python -m agent "tags"                    # 2. 浏览标签体系
python -m agent "filter [精华] [科技]"     # 3. 交叉过滤定位
python -m agent "lookup AI agent"         # 4. 全文检索
```

### 写作辅助

```bash
python -m agent "filter [职场] [策略]"      # 找相关笔记
python -m agent "lookup 职业规划"           # 精确查找
python -m agent "fetch https://..."        # 抓取参考资料入库
```

### 认知复盘

```bash
python -m agent "list"                     # 浏览全部 249 篇文档
python -m agent "filter [认知] [建模]"      # 聚焦认知类笔记
python -m agent "hybrid 个人主权系统"        # 语义深度搜索
```

### Linux 文件工具

```bash
python -m agent "tree skills -L 2"                           # 目录树
python -m agent "find skills -name *.py -maxdepth 1"         # 按名查找
python -m agent "grep -rn \"import\" tests/"                 # 递归搜索
python -m agent "find_grep skills --name *.py --pattern TODO -r -n"  # find | grep
python -m agent "build similarity edges"                     # 构建 BM25 相似图
```

---

## 编程式调用

### 快速启动 — `build_agent()` 工厂（推荐）

所有 skill/MCP 装配集中在 `harness/factory.py`，`python -m agent` 和 `server.py` 内部均使用此工厂：

```python
from harness.factory import build_agent

agent = build_agent()  # 读取 env，注册全部 skill + MCP，bootstrap 记忆

out = agent.handle("calc 2 + 2")
# {"ok": True, "result": 4.0, "error": None}
```

### 手动装配（完全控制）

```python
from agent import AgentCore
from skills.math_logic import MathLogic
from skills.file_ops import FileOps
from skills.fetch_web_to_md import FetchWebToMd
from skills.context import ContextSkill
from skills.reflect import ReflectSkill       # Phase 6
from skills.review import ReviewSkill         # Phase 5
from skills.find_ops import FindOps
from skills.grep_ops import GrepOps
from skills.tree_ops import TreeOps
from skills.pipeline_ops import PipelineOps
from skills.react import ReactSkill
from mcp.servers.knowledge_server import KnowledgeServer
from mcp.servers.hybrid_knowledge_server import HybridKnowledgeServer
from mcp.servers.file_search_server import FileSearchServer
from rag.corpus_loader import CorpusLoader
from rag.metadata import MetadataIndex
from rag.embedder import get_embedder
from rag.fts_index import FtsIndex
from memories.url_registry import UrlRegistry

# 双 loader：knowledge 用完整文档，hybrid 用 chunks
corpus = CorpusLoader("rag/corpus", chunk=False)
corpus_chunked = CorpusLoader("rag/corpus", chunk=True, chunk_size=1200, chunk_overlap=150)
meta = MetadataIndex("rag/corpus")
meta.build()
fts = FtsIndex("rag/fts_index.db")
url_registry = UrlRegistry("memories/url_map.db")

agent = AgentCore(
    rules_path="config/rules.yaml",
    routing_path="config/routing.yaml",
    cache_path="memories/cache.db",
    short_term_path="memories/short_term.json",
    long_term_path="memories/long_term.db",
)
agent.register_skill("math_logic", MathLogic())
agent.register_skill("file_ops", FileOps())
agent.register_skill("fetch_web", FetchWebToMd(url_registry=url_registry))
agent.register_skill("context", ContextSkill())
agent.register_skill("reflect", ReflectSkill())    # Phase 6
agent.register_skill("review", ReviewSkill())      # Phase 5
agent.register_skill("find_ops", FindOps())
agent.register_skill("grep_ops", GrepOps())
agent.register_skill("tree_ops", TreeOps())
agent.register_skill("pipeline_ops", PipelineOps())
agent.register_skill("react", ReactSkill(agent=agent))
# Phase 7: graph_db_path 启用 chunks / chunks_by_cat op
agent.register_mcp("knowledge", KnowledgeServer(
    corpus, metadata=meta, fts_index=fts,
    graph_db_path="rag/graph_index.db",
))
agent.register_mcp("hybrid_knowledge", HybridKnowledgeServer(corpus_chunked, embedder=get_embedder()))
agent.register_mcp("file_search", FileSearchServer())

# 自举项目元数据（幂等，仅首次写入长期记忆）
agent.bootstrap_memory()

out = agent.handle("calc 12 * 12")
# {"ok": True, "result": 144, "error": None}
```

### 直接调用 Skill（绕过路由 / 缓存）

```python
from skills.math_logic import MathLogic
MathLogic().execute({"op": "calc", "expr": "2+2"})
```

### 直接调用 MCP

```python
from mcp.mcp_client import MCPClient
from mcp.servers.knowledge_server import KnowledgeServer
from rag.metadata import MetadataIndex

meta = MetadataIndex("rag/corpus")
meta.build()
client = MCPClient()
client.register("knowledge", KnowledgeServer("rag/corpus", metadata=meta))
client.list_tools()        # ["knowledge"]
client.call("knowledge", {"op": "lookup", "query": "python"})
client.call("knowledge", {"op": "filter", "tags": ["精华", "科技"]})
```

---

## 记忆与缓存

### 短期记忆（JSON Buffer）

```python
from memories.short_term import ShortTerm
mem = ShortTerm("memories/short_term.json", max_entries=50)
mem.append("user", "hello")
mem.append("assistant", '{"ok": true, ...}')
mem.recent(10)     # 返回最近 10 条 [{role, content, ts}, ...]
mem.clear()        # 清空并持久化
```

### 长期记忆（SQLite 三元组）

```python
from memories.long_term import LongTerm
db = LongTerm("memories/long_term.db")
db.add("user", "prefers", "dark_mode")
db.query(subject="user")              # [("user", "prefers", "dark_mode"), ...]
db.query(predicate="prefers")         # 同上
db.summarize_as_text()                # "user prefers dark_mode\n..."
```

每次 `agent.handle` 成功后会自动写入两条三元组：
- `(user, asked, <query>)`
- `(assistant, answered, <result_json>)`

### 语义缓存

```python
from harness.cache_guard import CacheGuard
cache = CacheGuard("memories/cache.db", ttl_seconds=3600)
cache.set("hello world", {"ok": True, "result": 42, "error": None})
cache.get("  Hello   WORLD  ")   # 命中（归一化 + SHA256）
cache.clear()
```

**清空缓存**：
```bash
rm ai-agent-core/memories/cache.db
```

---

## 常见工作流

### 1. 批量抓取网页 → 自动入库 → 检索

```bash
cd ai-agent-core
# 抓取即入库：fetch 默认输出到 rag/corpus/
python3 -m agent "fetch https://a.com"
python3 -m agent "fetch https://b.com"

# 注意：KnowledgeServer 在 AgentCore 启动时加载 corpus，
# 同一进程内新抓的文件需重启或重新 register_mcp 才能被 lookup 识别。
# CLI 每次都是新进程，所以下一条 lookup 能看到新文件：
python3 -m agent "lookup react"

# 如需清洗某个文件（如去除抓取产生的多余空行），clean file 输出仍落回 corpus：
python3 -m agent "clean file rag/corpus/20260707_120000_a.com.md"
# ⚠️ 注意：clean file 会覆盖原文件（写回相同路径）
```

### 2. 数学计算 → 验证缓存命中

```bash
python3 -m agent "calc 6 * 7"        # 第一次：miss → 调 skill → 写缓存
python3 -m agent "calc 6 * 7"        # 第二次：cache hit，跳过 skill
```

验证：第二次响应时间应明显更短（< 5ms）。

### 3. 知识库检索 → LLM 总结（混合路径）

```bash
# 1. 先用 lookup 拿到相关文档（确定性）
python3 -m agent "lookup react hooks"

# 2. 把检索结果作为 context，让 LLM 总结（需 API key）
python3 -m agent "explain react hooks in 3 sentences"
```

### 4. 查询历史对话

```python
from memories.short_term import ShortTerm
mem = ShortTerm("memories/short_term.json")
for m in mem.recent(20):
    print(f"[{m['role']}] {m['content'][:80]}")
```

### 5. 清空所有运行时状态

```bash
cd ai-agent-core
rm -f memories/cache.db memories/short_term.json memories/long_term.db
# 注意：rag/corpus/ 下的文件是知识库内容，不要误删
```

### 6. ReAct 多步推理

```bash
# LLM 自主驱动：先算数，再查找文件
python3 -m agent "react 先算 10/2，再 find *.md 文件"

# 限制工具集 + 步数
python3 -m agent "react 分析知识库 --allowed-tools skill_math_logic mcp_knowledge --max-steps 3"
```

---

## HTTP API

FastAPI + uvicorn 暴露 `AgentCore.handle()` 为 HTTP 接口，便于外部系统调用。AgentCore 非线程安全，所有 `/query` 请求通过 `threading.Lock` 串行化。

### 启动 / 停止

```bash
cd ai-agent-core

# 前台运行（调试用，Ctrl-C 退出）
python3 server.py run --port 8000 --host 127.0.0.1

# 后台启动（写 PID 到 memories/server.pid，日志到 memories/server.log）
python3 server.py start

# 查看状态
python3 server.py status

# 停止 / 重启
python3 server.py stop
python3 server.py restart --port 9000
```

环境变量覆盖：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SERVER_HOST` | `127.0.0.1` | 监听地址 |
| `SERVER_PORT` | `8000` | 监听端口 |
| `SERVER_PID_FILE` | `memories/server.pid` | PID 文件路径 |
| `SERVER_LOG_FILE` | `memories/server.log` | 日志文件路径 |

### 端点

**`POST /query`** — 执行 query，返回信封：

```bash
curl -s -X POST http://127.0.0.1:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "calc 2+2"}'
# {"ok": true, "result": 4, "error": null}
```

**`GET /health`** — 健康检查：

```bash
curl -s http://127.0.0.1:8000/health
# {"ok": true}
```

### Python 客户端示例

```python
import requests
r = requests.post("http://127.0.0.1:8000/query", json={"query": "lookup python"})
print(r.json())
```

---

## Review Cron 守护进程

定时调度 `ReviewSkill` 对每个 L1 分类做认知审计，报告写入 `reviews/` 目录。使用 stdlib 轮询调度（`time.sleep` + `threading.Event`），不依赖 APScheduler。

### 启动 / 停止

```bash
cd ai-agent-core

# 前台运行（调试用，立即跑一次 cycle）
python3 review_cron.py run

# 后台启动（每 24 小时跑一次）
python3 review_cron.py start

# 查看状态
python3 review_cron.py status

# 停止 / 重启
python3 review_cron.py stop
python3 review_cron.py restart --every-hours 12

# 自定义间隔（每小时一次）
REVIEW_CRON_EVERY_HOURS=1 python3 review_cron.py start
```

### 一次 cron cycle 做什么

1. 调 `build_agent()` 构造 AgentCore 实例
2. 从 `rag/graph_index.db` 查 distinct `l1` 列表（`SELECT DISTINCT l1 FROM document_graph`）
3. 对每个 l1 调 `ReviewSkill.execute({op:"review", l1:..., graph_db_path:..., cache_db_path:...})`
4. 把 report 写到 `reviews/YYYYMMDD_HHMMSS_<l1>.md`

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `REVIEW_CRON_EVERY_HOURS` | `24` | 触发间隔（小时） |
| `REVIEW_CRON_POLL_SECONDS` | `60` | 轮询周期（秒），控制停机响应延迟 |
| `REVIEW_CRON_PID_FILE` | `memories/review_cron.pid` | PID 文件 |
| `REVIEW_CRON_LOG_FILE` | `memories/review_cron.log` | 日志文件 |
| `REVIEWS_DIR` | `reviews` | 报告输出目录 |

### 产物示例

```bash
ls reviews/
# 20260709_030000_历史.md
# 20260709_030000_科技.md
# 20260709_030001_职场.md
```

每份报告即一次 `ReviewSkill` 的 LLM 审计结果，可离线浏览或归档。

---

## 错误处理

所有错误都通过信封返回，**不会抛异常**给调用方：

```python
# skill 错误
{"ok": False, "result": None, "error": "no such file: /tmp/missing.txt"}

# MCP 错误
{"ok": False, "result": None, "error": "unknown tool: foo"}

# LLM 错误（无 API key）
{"ok": False, "result": None, "error": "ANTHROPIC_API_KEY not set"}

# 路由兜底（不应发生，routing.yaml 末尾有 .* 兜底）
{"ok": False, "result": None, "error": "no routing match"}
```

## 验证安装

```bash
cd ai-agent-core
python3 -m pytest -q               # 应通过 357 个测试
python3 -m agent "calc 12 * 12"    # 应返回 {"ok": true, "result": 144, ...}
python3 -m agent "tree skills -L 1" # 验证 find/grep/tree skill
python3 server.py run --port 8000  # 另起 shell：curl -s localhost:8000/health
```

---

## Watcher Pipeline（自动入库）

独立后台进程监控 `rag/corpus/`，新文件/修改文件自动触发：文本清洗 → 规则打 L1/L2/L3 标签 → 注入 YAML frontmatter → upsert 进 SQLite FTS5 → upsert 进 SQLite `document_graph`（L1→L2→L3→L4 图索引）→ upsert `knowledge_edges`（Phase 4 wikilinks）→ upsert `document_chunks`（Phase 7 L5 chunks）。

**Phase 演进**：
- **Phase 1（已完成）**：`KnowledgeServer` 集成 `FtsIndex`，`lookup` 优先走 FTS5，BM25 兜底
- **Phase 2（已完成）**：图索引从 `config/index.yaml` 迁移到 `rag/graph_index.db`（SQLite WAL，原生并发安全），`config/index.yaml` 降级为只读快照
- **Phase 3（已完成）**：`on_deleted` 事件自动清理 FTS5 + graph_index（`delete_file_indexes()`）
- **Phase 4（已完成）**：Multi-homing（同 path 多标签）+ `knowledge_edges` 表（`[[wikilinks]]` 解析）+ 代码块内 wikilink 保护
- **Phase 5（已完成）**：`ReviewSkill` — 按分类批量打包 + LLM 认知审计 + 24h 缓存
- **Phase 6（已完成）**：`ReflectSkill` — 实践复盘追加 + `revisions` frontmatter（24h 幂等）
- **Phase 7（已完成）**：L5 `document_chunks` 表 + `chunks`/`chunks_by_cat` op + 离线 Ollama 分类回退

### 启动 Watcher

```bash
cd ai-agent-core

# 后台启动（写 PID 到 ./.watcher.pid，日志到 ./.watcher.log）
python3 background_worker.py start --dir rag/corpus

# 查看状态
python3 background_worker.py status

# 停止 / 重启
python3 background_worker.py stop
python3 background_worker.py restart --dir rag/corpus --debounce-ms 300

# 前台运行（调试用，Ctrl-C 退出）
python3 background_worker.py run --dir rag/corpus
```

- 监控：`rag/corpus/` 递归（`WATCHER_DIR` 环境变量可覆盖）
- 防抖：500ms（`WATCHER_DEBOUNCE_MS`）
- 并发：2-worker 线程池 + SQLite WAL 模式（无需应用层锁）
- 退出：SIGINT / SIGTERM，优雅关闭

### URL 抓取入库

```bash
# 抓取 .md 写入 rag/corpus/，watcher 自动接管后续 pipeline
python3 -m scripts.web_scraper "https://example.com/article"

# 微信长文：下载图片 + 附件
python3 -m scripts.web_scraper "https://mp.weixin.qq.com/s/xxx" --save-img --save-attachments

# 不依赖 watcher：抓取后立即跑 pipeline
python3 -m scripts.web_scraper "https://example.com/article" --sync
```

`scripts/web_scraper.py` 复用 `skills.fetch_web_to_md` 的抓取函数（微信公众号专用 UA + 通用网页去噪，iframe/video/audio 转可点击链接占位）。

### 手动跑 pipeline

```bash
python3 -m scripts.pipeline_worker --path rag/corpus/some_doc.md
```

返回信封：

```json
{
  "ok": true,
  "result": {
    "path": "rag/corpus/some_doc.md",
    "title": "...",
    "l1": "科技", "l2": "AI", "l3": "模型",
    "category": "科技/AI/模型",
    "index_yaml_added": true,
    "graph_added": true,
    "chars": 12345
  },
  "error": null
}
```

### FTS5 全文搜索

```bash
# CLI
sqlite3 rag/fts_index.db "SELECT path, title, category FROM docs WHERE docs MATCH 'llm' ORDER BY rank LIMIT 5"

# Python
python3 -c "
from rag.fts_index import FtsIndex
fts = FtsIndex('rag/fts_index.db')
for h in fts.search('llm', limit=5):
    print(h['path'], h['category'], h['snippet'][:80])
fts.close()
"
```

FTS5 表结构（`trigram` 分词器，支持中英文混合）：

```sql
CREATE VIRTUAL TABLE docs USING fts5(
    path, title, category, content, timestamp,
    tokenize = 'trigram'
);
```

- `path` — 文档绝对路径（PK，upsert 按 path DELETE+INSERT）
- `title` — 首个 `#` 标题
- `category` — `"L1/L2/L3"` 拼接字符串
- `content` — 清洗后正文
- `timestamp` — 入库 ISO 时间
- 短查询（< 3 字符，如中文 2 字"简历"）走 `instr()` substring 兜底

### 图索引 `rag/graph_index.db`（Phase 2 起）

SQLite `document_graph` 表，WAL 模式支持多线程并发写入：

```sql
CREATE TABLE document_graph (
    path     TEXT PRIMARY KEY,
    l1       TEXT NOT NULL,
    l2       TEXT NOT NULL,
    l3       TEXT NOT NULL,
    added_at TEXT NOT NULL,
    level    TEXT NOT NULL DEFAULT 'L4'
);
CREATE INDEX idx_l1l2l3 ON document_graph(l1, l2, l3);
PRAGMA journal_mode=WAL;
```

查询示例：

```bash
# 按 L1/L2/L3 过滤
sqlite3 rag/graph_index.db "SELECT path, added_at FROM document_graph WHERE l1='科技' AND l2='AI' AND l3='模型'"

# 统计每个 L3 主题下的文档数
sqlite3 rag/graph_index.db "SELECT l1, l2, l3, COUNT(*) FROM document_graph GROUP BY l1, l2, l3"

# 删除文件时清理（Phase 3 会自动处理）
sqlite3 rag/graph_index.db "DELETE FROM document_graph WHERE path = '/abs/path/to/deleted.md'"
```

`config/index.yaml` 现在是**只读快照**，由 `export_graph_to_yaml()` 一次性导出，不再实时写入：

```python
from scripts.pipeline_worker import export_graph_to_yaml
from pathlib import Path
count = export_graph_to_yaml(Path("rag/graph_index.db"), Path("config/index.yaml"))
print(f"exported {count} docs to config/index.yaml")
```

### KnowledgeServer + FTS5 集成（Phase 1）

`lookup` 现在三级降级：FTS5 → 子串匹配 → BM25：

```python
from rag.fts_index import FtsIndex
from mcp.servers.knowledge_server import KnowledgeServer

fts = FtsIndex("rag/fts_index.db")
srv = KnowledgeServer("rag/corpus", fts_index=fts)

# FTS5 优先，返回 snippet 高亮（而非完整正文）
out = srv.execute({"op": "lookup", "query": "llm"})
# {"ok": True, "result": "...<llm>...", "error": None}
```

agent.py 的 `main()` 已自动注入 `FtsIndex`，无需手动配置。

### 自动打标签 `config/tag_rules.yaml`

```yaml
defaults:
  l1: 未分类
  l2: Misc
  l3: General

rules:
  - l1: 科技
    l2: AI
    l3: 模型
    keywords: [ai, llm, gpt, claude, transformer, 大模型]
  # ...共 12 条规则
```

- 扫描 `title + content[:5000]` 小写化
- 按规则顺序，首个 keyword 命中即返回 `(l1, l2, l3)`
- 无命中返回 `defaults`
- 修改 yaml 后，下个文件事件即用新规则（每调用加载一次）

### Frontmatter 自动注入

无 frontmatter 的 `.md` 文件会被加上：

```yaml
---
l1: 科技
l2: AI
l3: 模型
title: <首个 # 标题>
fetched_at: <文件 mtime ISO>
---

<原正文>
```

已有 frontmatter 且含 `l1/l2/l3` 字段 → 不覆盖。

### 已知限制

- L5 节点（chunk、摘要）已实现（Phase 7 `document_chunks` 表 + `chunks`/`chunks_by_cat` op）
- 混合分类引擎：规则 → Ollama 本地小模型（Phase 7，opt-in，`OLLAMA_CLASSIFY_ENABLED=1` 启用）
- `on_deleted` 已在 Phase 3 实现自动闭环，无需手动清理
- Phase 4 wikilink 解析已保护代码块内 `[[...]]`，不会误建边

### Watcher Pipeline 测试

```bash
python3 -m pytest tests/test_pipeline_clean.py tests/test_pipeline_classify.py \
                  tests/test_pipeline_fts5.py tests/test_pipeline_index_yaml.py \
                  tests/test_graph_index.py tests/test_knowledge_server.py \
                  tests/test_pipeline_worker_e2e.py \
                  tests/test_phase4_graph_edges.py tests/test_phase5_review.py \
                  tests/test_phase6_reflect.py tests/test_phase7_chunks.py \
                  tests/test_phase7_offline_classifier.py \
                  tests/test_p1_similarity_edges.py tests/test_p1_pipeline_similarity_op.py \
                  tests/test_factory.py tests/test_react_skill.py \
                  tests/test_server.py tests/test_review_cron.py \
                  tests/test_tree_ops.py -v
```

## 参考

- 项目结构：[docs/struct.md](struct.md)
- README：[ai-agent-core/README.md](../ai-agent-core/README.md)
- 路由配置：[ai-agent-core/config/routing.yaml](../ai-agent-core/config/routing.yaml)
- 系统规则：[ai-agent-core/config/rules.yaml](../ai-agent-core/config/rules.yaml)
- 标签规则：[ai-agent-core/config/tag_rules.yaml](../ai-agent-core/config/tag_rules.yaml)
- 工厂装配：[ai-agent-core/harness/factory.py](../ai-agent-core/harness/factory.py)
