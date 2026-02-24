# Open WebUI Frontend Upgrade Plan (CrewAI Backend Preserved)

**Project:** Inara HR Assistant (HR_BOT_V1)  
**Date:** 2026-02-21  
**Objective:** Replace only the Chainlit frontend with Open WebUI while preserving all backend capabilities (CrewAI, RAG, cache, S3, RBAC logic, safety guards, logging).

---

## 1) Scope and Non-Negotiables

### In Scope
- Replace Chainlit UI with Open WebUI frontend.
- Keep CrewAI orchestration untouched.
- Keep existing backend logic and behavior parity (role-aware responses, RAG retrieval quality, semantic cache behavior, content safety).
- Keep Google SSO and role-aware access behavior.

### Out of Scope
- No re-architecture of `src/hr_bot/crew.py` business logic.
- No replacement of Hybrid RAG, semantic cache, or S3 loader internals.
- No functional redesign beyond the UI migration bridge.

---

## 2) Target Architecture

User Browser  
→ Open WebUI (frontend + auth + chat UX)  
→ Open WebUI Pipe Function (has access to `__user__`)  
→ FastAPI bridge service (`src/hr_bot/api/server.py`)  
→ Existing `HrBot.query_with_cache()`  
→ Existing CrewAI + tools + RAG + S3 + cache

This allows Open WebUI to be purely frontend + auth while the current intelligence stack remains as-is.

---

## 3) Functional Parity Matrix

### Must be Preserved
1. **CrewAI response quality and behavior**  
   - Use existing `HrBot` flow unchanged.
2. **RBAC (executive vs employee docs)**  
   - Role derived from email against existing allow-lists.
3. **S3 role-based document access**  
   - Continue using existing S3 prefixes and loader.
4. **Hybrid RAG behavior**  
   - Keep BM25 + vector fusion and index behavior.
5. **Semantic response caching**  
   - Keep thresholds, TTL, and store behavior.
6. **Content safety + policy exceptions**  
   - Keep current block/allow logic.
7. **Query logging/audit outputs**  
   - Preserve existing logging destination/format as closely as possible.

### Replaced UX Surface
- Chainlit chat UX → Open WebUI chat UX.
- Custom admin console usage can be reduced/transitioned in favor of Open WebUI admin for user and model operations; custom operational actions (cache clear/S3 refresh) stay available via backend endpoints.

---

## 4) Implementation Plan (Execution)

### Phase A — Backend Bridge API (FastAPI)
Create `src/hr_bot/api/server.py`:
- `GET /v1/models` (OpenAI-compatible model listing).
- `POST /v1/chat/completions` (OpenAI-compatible chat endpoint).
- Accept user identity from Open WebUI pipe payload.
- Derive role from email using existing allow-list logic.
- Reuse bot initialization caching by role.
- Call `query_with_cache()` and return OpenAI-style response payload.

Optional admin-compatible endpoints to preserve operational actions:
- `POST /admin/cache-clear`
- `POST /admin/s3-refresh`
- `POST /admin/rag-rebuild`

### Phase B — Open WebUI Pipe Function
Create `deploy/pipe_function.py`:
- Pipe receives `body` and `__user__`.
- Extract `__user__["email"]`.
- Forward request to FastAPI bridge with email + chat payload.
- Return response/stream in Open WebUI expected format.
- Keep endpoint URL configurable via valves.

### Phase C — Open WebUI Deployment
Create:
- `deploy/docker-compose.yml`
- `deploy/open-webui.env`

Configure:
- Google OAuth vars (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`).
- Signup/login policy per enterprise needs.
- Disable irrelevant providers/features where required.

### Phase D — Service Wiring
- Add `deploy/hr-bot-api.service` for FastAPI bridge.
- Keep service boundaries clean (Open WebUI container + Python backend service).
- Route traffic via existing reverse proxy.

### Phase E — Validation Checklist
1. SSO login succeeds.
2. User identity reaches backend from Open WebUI.
3. Role derivation correctly enforces executive/employee behavior.
4. RAG answers still include proper policy grounding/sources.
5. Cache hit behavior unchanged.
6. Safety filters behave as before.
7. Logs generated and readable.
8. Operational admin actions callable.

---

## 5) SSO and Identity Strategy

### Decision
Use Open WebUI Pipe Function with `__user__` identity and pass email explicitly to the backend bridge.

### Why
- Reliable identity source from Open WebUI runtime.
- Avoids brittle dependency on undocumented header-forwarding behavior.
- Keeps RBAC enforcement in backend where business logic already exists.

---

## 6) Security and Permissions Considerations

- Principle of least privilege during deployment and runtime.
- Ensure service user can read required config files and write only to intended log/cache directories.
- Keep OAuth secrets and API keys in env files with restricted permissions.
- Preserve existing content safety pipeline and PII protections.
- Avoid exposing internal admin endpoints without authentication/allow-list checks.

---

## 7) Risks and Mitigations

1. **Identity mismatch between frontend and backend**  
   - Mitigation: strict schema for `email`, reject missing/invalid users.
2. **Behavior drift in response formatting**  
   - Mitigation: adapter layer with deterministic formatting compatibility.
3. **Operational action regressions (cache/S3 refresh)**  
   - Mitigation: explicit admin endpoints + smoke tests.
4. **OAuth redirect misconfiguration**  
   - Mitigation: checklist with exact callback URL update in Google console.

---

## 8) Rollback Strategy

- Keep Chainlit entrypoint and service file available until final sign-off.
- If blocker occurs, re-enable existing Chainlit service and DNS/proxy mapping.
- Do not delete legacy UI files until stability window is completed.

---

## 9) Day-1 Execution Sequence

1. Build FastAPI bridge.
2. Add pipe function.
3. Deploy Open WebUI container with OAuth config.
4. Start bridge service.
5. Connect Open WebUI model to pipe.
6. Run full validation checklist.
7. Keep rollback switch ready for same-day fallback.

---

## 10) Deliverables

- `src/hr_bot/api/server.py`
- `deploy/pipe_function.py`
- `deploy/docker-compose.yml`
- `deploy/open-webui.env`
- `deploy/hr-bot-api.service`
- Validation report checklist (post-implementation)

---

## 11) Current Status

This document captures the approved migration strategy.  
Implementation begins only after this plan is accepted by stakeholders.
