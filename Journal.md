# Migration Journal — Open WebUI Frontend Upgrade

**Project:** HR_BOT_V1  
**Date Started:** 2026-02-21  
**Operator:** GitHub Copilot (GPT-5.3-Codex)

---

## Purpose of this Journal

This file is a running implementation journal for the Chainlit → Open WebUI frontend migration while preserving the CrewAI backend and all current behavior.

It records:
- What was investigated
- Key findings
- Decisions and rationale
- Permission/ownership checks
- Files planned/created
- Validation and rollout notes

---

## Entry 1 — Scope Confirmation

**Summary**
- User requested frontend-only migration to Open WebUI.
- User explicitly required CrewAI backend to remain untouched.
- User requested plan-first workflow before code changes.

**Interpretation locked in**
- Open WebUI is UI/auth shell.
- Existing `HrBot` stack remains the execution engine.
- Introduce thin API bridge rather than reworking core modules.

---

## Entry 2 — Codebase/Architecture Findings

### Existing backend components (to preserve)
- `src/hr_bot/crew.py` — core orchestration and safety/caching behavior.
- `src/hr_bot/tools/hybrid_rag_tool.py` — hybrid BM25 + vector retrieval.
- `src/hr_bot/tools/master_actions_tool.py` — procedural action retrieval.
- `src/hr_bot/utils/cache.py` — semantic response cache.
- `src/hr_bot/utils/s3_loader.py` — role-based S3 loading + ETag cache.

### Existing frontend/auth components
- `src/hr_bot/ui/chainlit_app.py` currently handles OAuth callback, role derivation, bot lifecycle, and query logging.
- Admin sub-app is currently mounted under Chainlit.

### Migration implication
- Must port only UI transport + auth entrypoint behavior.
- Keep backend logic paths and role checks equivalent.

---

## Entry 3 — Open WebUI Research Findings

### Confirmed
- Open WebUI supports OAuth (Google etc.) through env vars.
- Open WebUI supports custom Pipe functions.
- Pipe function receives `__user__` context (including identity fields like email).
- Open WebUI can proxy model-like behavior via Pipe without changing core backend.

### Key architectural decision
**Use Pipe Function → FastAPI bridge pattern**
- Pipe extracts user identity from `__user__`.
- Pipe forwards request + user email to backend bridge.
- Bridge enforces RBAC using existing allow-lists and existing `HrBot` logic.

### Why this decision
- Identity is explicit and deterministic.
- Avoids relying on uncertain user-header forwarding internals.
- Keeps all domain logic in current backend where it already lives.

---

## Entry 4 — Permission & Ownership Safety Check

Before creating files, environment ownership was verified.

### Commands run
- `id && whoami && pwd`
- `ls -ld /home /home/chat /home/chat/app /home/chat/app/HR_BOT_V1`
- `stat -c '%n | owner=%U group=%G mode=%a' /home/chat/app/HR_BOT_V1`

### Results
- Effective user: `root`.
- Working directory: `/home/chat/app/HR_BOT_V1`.
- Workspace directory owner/group: `root:root`.
- Workspace mode: `775`.

### Safety note
- Created files under workspace root are compatible with current ownership model in this environment.
- No permission escalation or ownership mutation was required for these document-only changes.

---

## Entry 5 — Files Created in this Session

1. `upgrade plan.md`
   - Contains finalized migration plan, architecture, phases, risk controls, rollback strategy, and deliverables.

2. `Journal.md`
   - This file; persistent implementation journal for tracking actions and findings.

---

## Entry 6 — Planned Implementation Files (Next Step)

When execution begins, expected additions are:
- `src/hr_bot/api/server.py` (FastAPI bridge)
- `src/hr_bot/api/__init__.py`
- `deploy/pipe_function.py` (Open WebUI pipe)
- `deploy/docker-compose.yml` (Open WebUI deployment)
- `deploy/open-webui.env` (Open WebUI env config)
- `deploy/hr-bot-api.service` (systemd service)

These are not yet created in this session.

---

## Entry 7 — Validation Plan (Post-Implementation)

- Verify Google SSO login on Open WebUI.
- Verify user email is received by backend via pipe payload.
- Verify role derivation and role-specific docs access.
- Verify retrieval quality and source grounding remain equivalent.
- Verify cache behavior and performance expectations.
- Verify safety filters and PII protections are intact.
- Verify operational actions (cache clear / S3 refresh) remain accessible.

---

## Entry 8 — Journal Usage Convention

For future entries, use:
- **Date/Time**
- **Action** (what changed)
- **Reason** (why)
- **Result** (what happened)
- **Follow-up** (what is next)

This keeps deployment traceability clean for client handoff and audits.

---

## Current Session Status

- Requested documentation files were created successfully.
- No runtime/service code was modified yet.
- Migration execution is ready to begin on approval.

---

## Entry 9 — Implementation Started (Approved)

**Action**
- Began code implementation after explicit approval.
- Built FastAPI bridge package under `src/hr_bot/api/`.

**What was added**
- `src/hr_bot/api/__init__.py`
- `src/hr_bot/api/main.py`
- `src/hr_bot/api/server.py`

**How it was implemented**
- Exposed OpenAI-compatible endpoints:
   - `GET /v1/models`
   - `POST /v1/chat/completions`
- Preserved role derivation logic via `EXECUTIVE_EMAILS` / `EMPLOYEE_EMAILS`.
- Preserved backend execution path through `HrBot.query_with_cache()`.
- Preserved response formatting and query logging compatibility.
- Added operational endpoints for admin-only maintenance:
   - `POST /admin/cache-clear`
   - `POST /admin/s3-refresh`
   - `POST /admin/rag-rebuild`

**Reason**
- Open WebUI needs an API endpoint to call while keeping CrewAI logic untouched.

**Result**
- Bridge layer now exists and is runnable via `uv run api_server`.

---

## Entry 10 — Open WebUI Integration Artifacts

**Action**
- Added Open WebUI integration and deployment files.

**What was added**
- `deploy/pipe_function.py`
- `deploy/docker-compose.yml`
- `deploy/open-webui.env`
- `deploy/hr-bot-api.service`

**How it was implemented**
- Pipe function uses Open WebUI `__user__` context and forwards `email` to backend.
- Pipe forwards request payload to `/v1/chat/completions` and returns backend response.
- Docker Compose deploys Open WebUI with persisted data volume.
- Environment template includes OAuth and OpenAI-compatible backend base URL wiring.
- Systemd unit added for API bridge service.

**Reason**
- This enables frontend swap without touching CrewAI internals.

**Result**
- End-to-end integration path is now codified in-repo.

---

## Entry 11 — Documentation Updates

**Action**
- Updated `README.md` to include Open WebUI + API bridge path.

**What changed**
- Added Open WebUI feature section.
- Added recommended deployment path for Open WebUI + API bridge.
- Updated project structure to include new API/deploy artifacts.

**Reason**
- Ensure operators can deploy the new frontend path consistently.

**Result**
- Primary documentation now reflects both existing rollback path and new frontend architecture.

---

## Entry 12 — Validation & Smoke Test

**Action**
- Performed static and runtime checks after implementation.

**Checks executed**
- IDE diagnostics on new files (`get_errors`) reported no issues.
- Started API bridge locally with uvicorn.
- Verified endpoints:
   - `GET /health` → `200` with `{"status":"ok"}`
   - `GET /v1/models` → `200` with model list payload
- Verified RBAC gate:
   - `POST /v1/chat/completions` with unauthorized email → `403`

**Result**
- Bridge boots successfully.
- Baseline endpoints and access controls behave as expected.
- Test process was stopped cleanly after verification.

**Follow-up**
- Next validation stage is full integrated test with Open WebUI container + uploaded pipe function + authorized test users.

---

## Entry 13 — Live Bring-Up (API + Open WebUI)

**Action**
- Proceeded with full runtime bring-up in the test environment.

**What happened**
1. Docker was not present initially.
2. Installed Docker Engine and docker-compose CLI.
3. Started API bridge via uvicorn on port `8502`.
4. Started Open WebUI via `deploy/docker-compose.yml`.

**Issue encountered**
- Open WebUI container could not reach backend through `host.docker.internal` while using bridge networking in this host setup.

**Fix applied**
- Switched Open WebUI service to `network_mode: host` (test-environment focused).
- Updated Open WebUI env values:
   - `WEBUI_URL=http://localhost:8080`
   - `OPENAI_API_BASE_URL=http://127.0.0.1:8502/v1`
   - `CORS_ALLOW_ORIGIN=http://localhost:8080`
- Enabled test-login path while OAuth creds are blank:
   - `ENABLE_SIGNUP=true`
   - `ENABLE_LOGIN_FORM=true`
   - `ENABLE_OAUTH_SIGNUP=false`

**Additional quality fix**
- Added explicit `load_dotenv()` in `src/hr_bot/api/server.py` so local API runs load RBAC/env settings consistently.

**Validation results**
- Open WebUI endpoint: `http://127.0.0.1:8080` → HTTP 200.
- Container-to-backend connectivity check from inside Open WebUI container to `http://127.0.0.1:8502/health` succeeded.
- Authorized API chat call using allow-listed employee email returned HTTP 200 and assistant response.

**Current runtime status**
- API bridge is running in background on `:8502`.
- Open WebUI container is running and healthy on `:8080`.

---

## Entry 14 — Public Domain Cutover (`chat.testingurl.cloud`)

**Action**
- Investigated why public URL still showed previous behavior.

**Findings**
- Nginx vhost `chat.testingurl.cloud.conf` still proxied to Chainlit on `127.0.0.1:8501`.
- `chat-chainlit.service` was still active, and `hr-bot-api.service` was not installed in systemd.

**Changes applied**
1. Updated nginx proxy target for `chat.testingurl.cloud` to Open WebUI (`127.0.0.1:8080`).
2. Validated nginx config and reloaded nginx.
3. Installed systemd unit:
    - copied `deploy/hr-bot-api.service` → `/etc/systemd/system/hr-bot-api.service`
    - enabled and started `hr-bot-api.service`
4. Stopped `chat-chainlit.service` to avoid dual frontend confusion.

**Validation**
- `https://chat.testingurl.cloud` returns HTTP 200 with `text/html` (Open WebUI frontend).
- `http://127.0.0.1:8502/health` returns `{"status":"ok"}`.
- Service state:
   - `nginx`: active
   - `hr-bot-api.service`: active
   - `chat-chainlit.service`: inactive

   ---

   ## Entry 15 — Stream Error + SSO Enablement (Post-Cutover)

   **Action**
   - Addressed two reported issues:
      1) Open WebUI error banner for `stream=true`.
      2) Need Google SSO sign-in option on live login.

   **Changes applied**
   1. Updated API bridge stream handling in `src/hr_bot/api/server.py` to return SSE-style OpenAI chunks instead of rejecting stream requests.
   2. Updated `deploy/pipe_function.py` backend default URL to `http://127.0.0.1:8502` (host-network deployment compatibility).
   3. Updated `deploy/open-webui.env` auth settings and Google OAuth values:
       - `ENABLE_OAUTH_SIGNUP=true`
       - `ENABLE_LOGIN_FORM=true`
       - `ENABLE_SIGNUP=false`
       - `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` loaded from `.env`
       - `GOOGLE_OAUTH_REDIRECT_URI=https://chat.testingurl.cloud/oauth/google/callback`
   4. Restarted backend service and Open WebUI container.

   **Result**
   - New runtime regression appeared during stream test: backend `500` while initializing retrieval stack.

   ---

   ## Entry 16 — Root Cause & Final Fix for Stream 500

   **Root cause found**
   - Backend logs showed:
      - `sqlite3.OperationalError: attempt to write a readonly database`
   - Failure occurred while creating disk cache under repository-local paths (`.rag_cache` / `.rag_index`) during `HrBot` initialization.
   - Service runs as `chat`, but cache directories were owned by `root:root`.

   **Fix applied**
   - Corrected ownership for runtime cache/index paths:
      - `.rag_cache`
      - `.rag_index`
      - `.master_actions_index`
      - `storage/response_cache`
   - Restarted `hr-bot-api.service`.
   - Aligned Open WebUI production URL settings in `deploy/open-webui.env`:
      - `WEBUI_URL=https://chat.testingurl.cloud`
      - `CORS_ALLOW_ORIGIN=https://chat.testingurl.cloud`
      - restarted Open WebUI container to apply.

   **Validation**
   - Authorized stream request now succeeds and returns SSE chunks with `data: ...` followed by `data: [DONE]`.
   - Live public config endpoint confirms OAuth provider presence:
      - `https://chat.testingurl.cloud/api/config` includes `"oauth":{"providers":{"google":"google"}}`.
   - Public site responds HTTP 200.

   **Operational note**
   - Avoid running cache/index generation as `root` when the runtime service user is `chat`, or re-apply ownership fix after root-level maintenance.

---

## Entry 17 — Fix for Infinite Loading on Chat Send

**Issue reported**
- User observed that chat messages stayed in loading state indefinitely with no visible error.

**Investigation findings**
- Backend bridge was healthy (`/health`, `/v1/models`) and returned valid chat responses for allow-listed users.
- Role allow-lists were correct for current signed-in account.
- Root cause was in Pipe streaming behavior:
   - Pipe returned raw `response.iter_lines()` from backend SSE.
   - Open WebUI Pipe runtime expects yielded text chunks; raw SSE lines can leave UI waiting without rendering completion.

**Fix applied**
- Updated `deploy/pipe_function.py`:
   - Added `_stream_text_chunks()` to parse SSE `data:` lines.
   - Extracts `choices[0].delta.content` from chunk JSON and yields plain text chunks.
   - Stops cleanly on `[DONE]`.
- Corrected runtime logging permissions to remove backend write warnings:
   - `chown -R chat:chat data/logs`

**Validation**
- Direct smoke test of the updated Pipe stream path produced content chunks and terminated correctly.
- Backend non-stream and stream calls both return valid responses for authorized users.

**Deployment note**
- If the Pipe was previously uploaded in Open WebUI UI, re-upload/sync the updated `deploy/pipe_function.py` so runtime uses the fixed stream parser.

---

## Entry 18 — Finalizing v8 Release (Direct Pipe Injection, LTM Permissions, Google SSO)

**Issue reported**
- User still experienced infinite loading because the updated Pipe function needed to be applied directly to the running Open WebUI instance.
- Backend logs showed a silent `MEMORY ERROR: attempt to write a readonly database` when trying to save to Long Term Memory (LTM).
- Google SSO login failed with `Error 400: redirect_uri_mismatch`.

**Fix applied**
- **Direct Pipe Injection**: Wrote a Python script to directly update the `content` column in the `function` table of the Open WebUI SQLite database (`webui.db`) with the fixed `deploy/pipe_function.py` code. Restarted the `open-webui` Docker container to apply the changes immediately.
- **LTM Permissions**: Fixed the permissions of the `storage/long_term_memory.db` file by running `sudo chown -R chat:chat storage/`, allowing the backend to write conversation history successfully.
- **Google SSO**: Documented the correct redirect URIs required in the Google Cloud Console to fix the mismatch error:
  - `https://chat.testingurl.cloud/oauth/google/callback`
  - `https://chat.testingurl.cloud/auth/oauth/google/callback`

**Validation**
- Verified that the Open WebUI container restarted successfully and loaded the new Pipe function.
- Verified that the backend API successfully received chat requests and streamed responses without infinite loading.
- Verified that the LTM database error no longer appeared in the backend logs.
