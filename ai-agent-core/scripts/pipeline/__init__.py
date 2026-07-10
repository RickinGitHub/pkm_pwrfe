"""Pipeline scripts — ingestion sub-steps.

Holds scripts that implement stages of the document ingestion
pipeline (clean → classify → index). These are typically invoked by
``background_worker.py`` or run standalone for batch reprocessing.

NOTE: scripts currently in ``scripts/`` root (pipeline_worker.py,
offline_classifier.py) are NOT yet moved here — this package is
prepared for a future migration. See docs/telegram_bot_implementation_plan.md.
"""
