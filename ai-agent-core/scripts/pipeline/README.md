# scripts/pipeline/

入库流水线子步骤脚本。

## 定位

高内聚:所有服务于"文档入库 pipeline"的独立可执行脚本。
低耦合:只依赖 `rag/` 模块(`rag/fts_index.py`、`rag/graph_index.py`、`rag/chunker.py`),不互相直接调用,由 `background_worker.py` 或 CLI 顶层编排。

## 预期成员(待迁移,当前仍在 `scripts/` 根)

| 脚本 | 职责 | 触发方式 |
|------|------|---------|
| `pipeline_worker.py` | 单文档入库:清洗→打标→FTS5→graph→edges→chunks | watcher 事件 / 手动 |
| `offline_classifier.py` | 离线规则打标(L1/L2/L3) | pipeline 子步骤 / 独立批量 |

## 扩展点

未来归入此目录的脚本:
- 批量 reindex 工具
- chunk 重建脚本(改 chunk_size 后重切)
- 标签规则回归测试脚本

## 不放这里

- 相似度图构建 → `scripts/similarity/`
- 外部抓取 → `scripts/web/`
- 运维清理 → `scripts/maintenance/`
