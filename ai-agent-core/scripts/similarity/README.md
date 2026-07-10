# scripts/similarity/

相似度图构建脚本。

## 定位

高内聚:所有生成/刷新知识图谱相似度边的独立脚本。
低耦合:只依赖 `rag/graph_index.py` + `rag/corpus/`,不依赖 skills 或 mcp。

## 预期成员(待迁移,当前仍在 `scripts/` 根)

| 脚本 | 职责 | 触发方式 |
|------|------|---------|
| `build_similarity_edges.py` | BM25 相似度图(top-k 边) | 手动 / cron |

## 扩展点

未来归入此目录的脚本:
- 向量相似度图(基于 `rag/vector_db/store.py`)
- 社区发现 / 聚类
- 图重算 / vacuum

## 不放这里

- 入库子步骤 → `scripts/pipeline/`
- 抓取工具 → `scripts/web/`
