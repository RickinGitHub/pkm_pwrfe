# scripts/web/

外部网页抓取工具集。

## 定位

高内聚:所有从外部 URL 抓内容落地到 `rag/corpus/` 的独立脚本。
低耦合:只输出到 `rag/corpus/`,不直接调 agent / skills / mcp。

## 与 `skills/fetch_web_to_md.py` 的区别

| 维度 | `skills/fetch_web_to_md.py` | `scripts/web/` |
|------|----------------------------|----------------|
| 调用方 | `agent.handle("fetch <url>")` 路由 | 直接 python 执行 / cron |
| 场景 | Telegram 用户粘贴 URL / CLI | 批量、定时、一次性 |
| 依赖 | 走 AgentCore + UrlRegistry | 独立,自管去重 |

## 预期成员(待迁移,当前仍在 `scripts/` 根)

| 脚本 | 职责 | 触发方式 |
|------|------|---------|
| `web_scraper.py` | 通用网页抓取 → md | 手动 / 批量 |

## 扩展点

未来归入此目录的脚本:
- RSS 订阅抓取器
- Sitemap 全站抓取
- 微信公众号批量抓取
- 增量抓取(基于 UrlRegistry 的 diff)

## 不放这里

- 入库子步骤 → `scripts/pipeline/`
- 相似度图 → `scripts/similarity/`
