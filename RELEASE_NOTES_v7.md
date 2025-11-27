# Release Notes — v7.0 (Inara HR Assistant)

Release date: 2025-11-27

Overview
--------
v7.0 is a production-focused release that hardens security, fixes core retrieval bugs, improves caching semantics, and clarifies assistant identity.

Highlights
---------
- Production guards for input validation: empty/short query guard and configurable max query length (default 2500 chars).
- Assistant naming clarification: `Inara` is the assistant product name — responses refer to `your company` for employer references (prevents misattribution).
- RAG caching improvement: cache keys now include S3 version/ETag for deterministic invalidation on document changes.
- Hybrid RAG fix: chunk merging bug fixed to keep semantically connected passages together.
- PII protection: stronger detection and redaction for SSNs, credit card numbers, and other sensitive identifiers in memory and logs.
- Source handling: case-insensitive source matching and improved injection logic for citations.
- Misc: README updated to v7.0, tests improved, and minor UI/UX tweaks.

Upgrade Notes
-------------
1. Update your `.env` and secrets as usual.
2. Rebuild RAG indexes after upgrading (S3 version changed will auto-clear caches, but you can manually trigger via the UI "Refresh S3 Docs").
3. If you maintain pinned dependencies to exact versions (e.g., `sentence-transformers`, `torch`), verify compatibility with Python 3.10–3.13.

Credits
-------
Maintainer: Saish Shinde <saish.shinde15@gmail.com>
