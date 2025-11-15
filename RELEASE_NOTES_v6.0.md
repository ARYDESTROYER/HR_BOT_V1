
# Release Notes — v6.0

**Release date**: 2025-11-15

Summary
-------

v6.0 consolidates the recent v4.x/v5.x migration and focuses on making the HR Bot production-ready, with a secure Chainlit UI, hardened RBAC, S3 ETag smart caching, and further RAG improvements.

Key Highlights
--------------

- UI: Chainlit is the production UI surface; Streamlit is retained only as a legacy UI for emergency rollback (optional).
- Security & RBAC: Role-based allow-lists via `EXECUTIVE_EMAILS` and `EMPLOYEE_EMAILS`; `CHAINLIT_AUTH_SECRET` for session signing.
- Smart S3 Caching: ETag-based manifest, efficient LIST-based change detection, and manual refresh action in the UI.
- Hybrid RAG: BM25 + Semantic fusion, table-aware chunking, FAISS + local HF embeddings by default with optional external embedding providers.
- Packaging & Ops: `pyproject.toml` bumped to `6.0`; `uv` is recommended for dependency/venv management; Streamlit moved to a `legacy` optional extra.

Breaking Changes
----------------

- Chainlit replaces Streamlit as the production UI. If you depend on the Streamlit surface, install the legacy extras: `uv sync --extra legacy`.
- Streamlit is no longer a default dependency in `pyproject.toml`. CI and deployment pipelines should use `uv sync` to create `.venv`.

Quick Upgrade / Migration
-------------------------

1. From the repository root, create/update the `.venv` and install dependencies:

```bash
cd HR_BOT_V1
uv sync
crewai install
```

2. Run the development UI or adapt for your deployment:

```bash
crewai run  # or use chainlit/your production start command
```

3. Confirm RBAC & Auth settings in your `.env`:

```env
EXECUTIVE_EMAILS=alice@example.com,bob@example.com
EMPLOYEE_EMAILS=john@example.com
CHAINLIT_AUTH_SECRET=replace-me-with-chainlit-secret
```

4. If deploying, ensure the production `ENV` has `CHAINLIT_AUTH_SECRET`, OAuth client IDs/secrets, and provider settings. See README for complete env list and the example `deploy/chat-chainlit.service`.

Notes & Known Issues
--------------------

- OAuth 401 / login loops: often caused by RBAC deny (email not in allow-list) or a `CHAINLIT_AUTH_SECRET` mismatch; check server logs for `OAuth login rejected` messages and add the user email to allow-lists as required.
- Translations: if the UI briefly displays raw translation keys (e.g., `: credentialssignin`), ensure localization bundles in `.chainlit/translations/` contain the expected keys and casing.
- Large document set indexing may take longer and can be pre-built or done on a machine with more memory/Disk.

Security Considerations
-----------------------

- `CHAINLIT_AUTH_SECRET` must be kept secret; rotating it resets sessions. Avoid broadcasting or committing secrets.
- Use dedicated, least-privileged AWS IAM credentials for S3 & Bedrock access in production.

Contributors & Acknowledgements
--------------------------------

Thanks to the engineering and product teams for the Chainlit migration, the S3 caching design, and RAG improvements.

Where to find more details
-------------------------

- Core deployment and environment guidance: `README.md` (Chainlit Deployment Guide section)
- Quick Setup: `QUICKSTART.md`
- S3 caching details: `S3_CACHE_IMPLEMENTATION.md`
