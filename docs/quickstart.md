# Quickstart

## Step 0 — 环境准备

```bash
cd ai-agent-core

# 安装依赖
pip install -e ".[dev]"

# 配置环境变量（可选，仅 LLM 兜底 / Review / React 需要 API key）
cp .env.example .env
# 编辑 .env，填入 ANTHROPIC_API_KEY=sk-ant-xxxxx
```

## Step 1 — 验证安装

```bash
# 算术验证（确定性 skill，零 token）
python3 -m agent "calc 2 + 2"
# 预期: {"ok": true, "result": 4, "error": null}

# 目录树验证
python3 -m agent "tree skills -L 1"

# 跑测试套件
python3 -m pytest -q
```

## Step 2 — 启动 Watcher（自动入库后台进程）

```bash
# 后台启动，监控 rag/corpus/ 目录
python3 background_worker.py start --dir rag/corpus

# 确认状态
python3 background_worker.py status
```

> Watcher 监听文件创建/修改/删除事件，自动执行：清洗 → 打标签 → 注入 frontmatter → FTS5 索引 → graph_index → wikilink 边 → L5 chunks。

## Step 3 — 抓取网页入库

```bash
# 抓取网页 → 自动写入 rag/corpus/ → watcher 自动索引
python3 -m agent "fetch https://example.com/article"

# 微信公众号文章
python3 -m agent "fetch https://mp.weixin.qq.com/s/xxx"

# 下载图片 + 附件
python3 -m scripts.web_scraper "https://mp.weixin.qq.com/s/xxx" --save-img --save-attachments

# 重复抓取同一 URL 自动去重（返回缓存路径）
python3 -m agent "fetch https://example.com/article"
```

## Step 4 — 知识库检索

```bash
# FTS5 全文搜索（优先 FTS5 → 子串兜底 → BM25）
python3 -m agent "lookup python"
python3 -m agent "搜索 大模型"

# 标签过滤（AND 交叉）
python3 -m agent "filter [精华] [科技]"

# 浏览全部文档
python3 -m agent "list"

# 查看所有标签
python3 -m agent "tags"

# 混合 RAG（BM25 + 向量融合）
python3 -m agent "hybrid 个人主权系统"

# L5 chunk 级检索
python3 -m agent "chunks rag/corpus/foo.md"
python3 -m agent "chunks_by_cat 科技 AI 模型"
```

## Step 5 — 文件操作

```bash
# 目录树
python3 -m agent "tree . -L 2"

# find 风格查找
python3 -m agent "find skills -name *.py -maxdepth 1"

# grep 风格搜索
python3 -m agent "grep -rn \"import\" tests/"

# find | grep 管道
python3 -m agent "find_grep skills --name *.py --pattern TODO -r -n"
```

## Step 6 — 上下文恢复（新窗口第一步）

```bash
# 零 token 恢复项目快照 + 最近对话
python3 -m agent "context"
```

## Step 7 — 认知审计（需 API key）

```bash
# 按分类批量打包文档 → LLM 审计（24h 缓存）
python3 -m agent "review 科技 AI 模型"

# 仅打包不调 LLM（debug）
python3 -m agent "review 科技 AI 模型 --dry-run"

# 聚焦子主题
python3 -m agent "review 历史 中国 朝代 --query 聚焦治理模式"
```

## Step 8 — 实践复盘

```bash
# 向笔记追加实践复盘段（24h 去重）
python3 -m agent "reflect rag/corpus/foo.md --insight 这个模式与汉代监察制度同构"
```

## Step 9 — ReAct 多步推理（需 API key）

```bash
# LLM 自主驱动多步任务
python3 -m agent "react 先算 10/2，再 find *.md 文件"

# 限制工具集 + 步数
python3 -m agent "react 分析知识库 --allowed-tools skill_math_logic mcp_knowledge --max-steps 3"
```

## Step 10 — 启动 HTTP API

```bash
# 后台启动
python3 server.py start

# 测试
curl -s http://127.0.0.1:8000/health
# {"ok": true}

curl -s -X POST http://127.0.0.1:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "calc 2+2"}'
# {"ok": true, "result": 4, "error": null}

# 停止
python3 server.py stop
```

## Step 11 — 编程式嵌入

```python
from harness.factory import build_agent

agent = build_agent()  # 一行启动，自动注册全部 skill + MCP

out = agent.handle("calc 2 + 2")
# {"ok": True, "result": 4.0, "error": None}

out = agent.handle("lookup python")
out = agent.handle("fetch https://example.com")
```

## Step 12 — 批量回灌存量文件（可选）

```bash
# watcher 只处理事件，不扫描启动前已有文件
# 一次性回灌所有 .md：
find rag/corpus -name '*.md' -type f -print0 | \
    xargs -0 -I{} -P4 python3 -m scripts.pipeline_worker --path "{}"
```

## Step 13 — 构建 BM25 相似度图（可选）

```bash
# 为每篇文档计算 top-5 最相似文档，写入 knowledge_edges
python3 -m agent "build similarity edges"
```

## Step 14 — Review Cron 守护进程（可选）

```bash
# 后台启动，每 24h 自动审计每个 L1 分类
python3 review_cron.py start

# 查看状态
python3 review_cron.py status

# 报告产物在 reviews/ 目录
ls reviews/
```

## Step 15 — 停止所有后台进程

```bash
python3 background_worker.py stop    # 停 watcher
python3 server.py stop               # 停 HTTP API
python3 review_cron.py stop          # 停 review cron
```

---

## 最小可用路径（3 步上手）

```bash
cd ai-agent-core
pip install -e ".[dev]"

# 1. 启动 watcher
python3 background_worker.py start --dir rag/corpus

# 2. 抓取一篇文章
python3 -m agent "fetch https://example.com/article"

# 3. 检索
python3 -m agent "lookup article"
```

所有命令返回统一信封 `{"ok": bool, "result": Any, "error": str|null}`，不会抛异常。无 `ANTHROPIC_API_KEY` 时确定性 skill 正常工作，仅 LLM 兜底/Review/React 返回明确错误。
