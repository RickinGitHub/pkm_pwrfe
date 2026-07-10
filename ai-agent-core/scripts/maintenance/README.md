# scripts/maintenance/

运维清理与健康检查脚本。

## 定位

高内聚:所有针对持久化状态(SQLite、corpus、memories)的清理/vacuum/体检脚本。
低耦合:只读为主;写操作脚本必须显式执行,不被其他进程自动调起。

## 预期成员(暂无,规划中)

| 脚本 | 职责 | 触发方式 |
|------|------|---------|
| `cleanup_db.py` | SQLite vacuum + WAL checkpoint | 手动 / 定时 |
| `vacuum_corpus.py` | 清理孤儿 corpus 文件(无 FTS5 索引) | 手动 |
| `health_check.py` | 体检:DB 连接 / 索引完整性 / 磁盘水位 | cron / 部署前 |
| `cleanup_sessions.py` | 清理过期 telegram sessions | cron |

## 扩展点

- 部署前自检脚本
- 数据迁移脚本(schema 升级)
- 备份/导出脚本

## 不放这里

- 入库子步骤 → `scripts/pipeline/`
- 相似度图 → `scripts/similarity/`
- 抓取工具 → `scripts/web/`

## 安全约定

所有写操作脚本必须:
1. 默认 `--dry-run`,显式 `--apply` 才真写
2. 打印将要执行的变更摘要
3. 支持 `--backup` 先备份再改
