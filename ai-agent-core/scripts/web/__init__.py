"""Web fetcher scripts.

Standalone web scrapers and fetchers that land content into
``rag/corpus/``. Distinct from ``skills/fetch_web_to_md.py`` which is
the agent-routed, Telegram/CLI-facing entry point — scripts here are
batch / scheduled / one-shot tools not invoked through agent.handle().

NOTE: scripts currently in ``scripts/`` root (web_scraper.py) are NOT
yet moved here — this package is prepared for a future migration.
"""
