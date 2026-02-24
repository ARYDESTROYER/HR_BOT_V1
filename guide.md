# Inara HR Assistant — Complete Project Guide

**Project:** Inara HR Assistant (HR_BOT_V1)  
**Current Version:** 7.1  
**Author / Maintainer:** Saish Shinde (saish.shinde15@gmail.com)  
**Repository:** https://github.com/ARYDESTROYER/HR_BOT_V1  
**License:** MIT  
**Document Created:** 2026-02-21  
**Last Updated:** 2026-02-21  

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Version History & Release Notes](#2-version-history--release-notes)
3. [Architecture](#3-architecture)
4. [Core Components](#4-core-components)
5. [Tools](#5-tools)
6. [UI Layer](#6-ui-layer)
7. [Admin Console](#7-admin-console)
8. [S3 Document Management & Caching](#8-s3-document-management--caching)
9. [Hybrid RAG System](#9-hybrid-rag-system)
10. [Semantic Response Caching](#10-semantic-response-caching)
11. [Security & Safety](#11-security--safety)
12. [Authentication & RBAC](#12-authentication--rbac)
13. [Configuration Reference](#13-configuration-reference)
14. [CLI Commands](#14-cli-commands)
15. [API Reference](#15-api-reference)
16. [Evaluation & Testing](#16-evaluation--testing)
17. [Deployment](#17-deployment)
18. [Costs & Performance](#18-costs--performance)
19. [Project Structure](#19-project-structure)
20. [Known Issues & Troubleshooting](#20-known-issues--troubleshooting)
21. [Dependencies](#21-dependencies)

---

## 1. Project Overview

Inara is a production-ready AI assistant for HR teams. It is powered by **CrewAI** for agent orchestration and **Amazon Bedrock Nova Lite** as the primary LLM. It provides:

- **Role-aware HR policy Q&A** — Executives and Employees see different document sets.
- **"How do I…?" guided workflows** — Pre-built actions (apply for leave, download payslip, etc.) via the Master Actions tool.
- **Hybrid RAG** — BM25 lexical search + vector search (`all-MiniLM-L6-v2` embeddings, FAISS index) over S3-hosted `.docx` documents.
- **Ultra-low-cost LLM** — Amazon Bedrock Nova Lite at ~$0.0002/query.
- **ETag-based S3 smart caching** — 93% cost reduction vs short-TTL approaches.
- **Semantic response caching** — Fuzzy keyword-based matching for instant repeat responses (72h TTL, 60–75% similarity threshold).
- **Chainlit Web UI** — OAuth (Google/Azure AD), real-time status, dark theme.
- **Admin Console** — Dashboard, cache management, query logs, user management, RAG status, settings (HTMX-based, no heavy JS).
- **Content safety** — Profanity filter, PII redaction, prompt injection defense, hallucination guards.
- **Long-term memory** — SQLite-backed conversation persistence for context continuity.
- **India-specific context** — General knowledge responses default to Indian laws, currency (₹ INR), and government schemes.

**Audience:** Enterprise HR / IT teams.  
**Primary Surface:** Chainlit web app (Streamlit retained for legacy rollback only).  
**Python:** 3.10–3.13 (3.12 recommended).  
**Package Manager:** `uv` (recommended).

---

## 2. Version History & Release Notes
### v8.0 (Current)

- **Open WebUI Pipe Fix**: Directly injected the updated `pipe_function.py` into the Open WebUI SQLite database to properly parse SSE streams and fix the infinite loading issue.

- **LTM Permissions**: Fixed `storage/long_term_memory.db` permissions to allow the backend to save conversation history without readonly memory errors.

- **Google SSO Configuration**: Documented the correct redirect URIs (`/oauth/google/callback` and `/auth/oauth/google/callback`) for Google Cloud Console to fix the `redirect_uri_mismatch` error.


### v8.0 (Current — Incremental over v7.0)

- **Admin Console** at `/admin/` — Dashboard, cache, logs, users, RAG, settings pages.
- **Message hardening** — `_author_as_string()` prevents `cl.User` objects from being serialized as author (fixes "author must be a string" error).
- **Input validation guards** — Empty/short queries (<3 chars) and overly long queries (>2500 chars, configurable) are blocked before processing.
- **Assistant naming fix** — `Inara` is the assistant name; employer always referred to as "your company."
- **S3 & cache improvements** — RAG cache keys include S3 version ETag hashes for deterministic invalidation.
- **Source handling** — Case-insensitive matching, no duplicate/partial matches for citations.
- **PII redaction** — Improved detection for SSNs, credit card numbers, and other identifiers in memory and logs.
- **Hybrid RAG fix** — Chunk merging bug fixed to prevent splitting semantically connected content.
- **Admin email RBAC** — `ADMIN_EMAILS` env var controls admin console access.

### v7.0 (Release date: 2025-11-27)

- Production guards for input validation.
- Assistant naming clarification (Inara ≠ company name).
- RAG caching tied to S3 ETag version for deterministic invalidation.
- Hybrid RAG chunk merging fix.
- Stronger PII detection and redaction.
- Case-insensitive source matching.
- README updated to v7.0, tests improved.

### v6.0 (Release date: 2025-11-15)

- **Chainlit becomes production UI** — Streamlit demoted to optional legacy (`uv sync --extra legacy`).
- **Role-based allow-lists** — `EXECUTIVE_EMAILS`, `EMPLOYEE_EMAILS`.
- **CHAINLIT_AUTH_SECRET** for session signing.
- **ETag-based S3 smart caching** — Manifest, version file, metadata.
- **Hybrid RAG** — BM25 + Semantic fusion, table-aware chunking, FAISS + local HF embeddings.
- **pyproject.toml** bumped to 6.0, `uv` recommended.

### S3 Cache Implementation (v4.3 — 2024-01-08)

- Original ETag-based caching system implemented.
- Three-layer cache files: `.cache_manifest`, `.s3_version`, `.cache_metadata.json`.
- 93% S3 cost reduction, 8–12x faster warm queries.
- Smart validation: manifest → version → TTL → file existence → ETag comparison.

---

## 3. Architecture

```
User Query (Role: Executive/Employee)
        ↓
┌───────────────────────┐
│     Chainlit UI       │
│  OAuth + RBAC Guard   │
│  Admin Actions        │
│  - Refresh S3 Docs    │
│  - Clear Resp Cache   │
└──────────┬────────────┘
           ↓
┌──────────────────────┐          ┌───────────────────┐
│      HR Bot          │          │  Admin Console    │
│   (CrewAI crew)      │          │  /admin/ (v8.0)   │
│  Nova Lite via       │          │  - Dashboard      │
│  Amazon Bedrock      │          │  - Cache mgmt     │
│  Semantic Caching    │          │  - Query logs     │
└──────────┬───────────┘          │  - User mgmt     │
           ↓                      └───────────────────┘
┌──────────────────────┐
│    Hybrid RAG Tool   │
│  Role-Based Filters  │
│  BM25 + Embeddings   │
└──────────┬───────────┘
           │
   ┌───────┼───────────────────────┐
   ↓       ↓                       ↓
┌─────────┐ ┌────────────────┐   ┌──────────────┐
│S3 Loader│ │ Vector Search  │   │ BM25 Search  │
│ETag     │ │ (MiniLM-L6-v2)│   │ (Lexical)    │
└────┬────┘ └───────┬────────┘   └──────┬───────┘
     │              │                    │
     └──────┬───────┴────────────────────┘
            ↓
      ┌───────────────┐
      │   FAISS Index │
      │   400+ chunks │
      └───────┬───────┘
              │
  ┌───────────┴────────────┐
  │    Local S3 Cache      │
  │  /tmp/hr_bot_s3_cache/ │
  │  .cache_manifest       │
  │  .s3_version (ETag)    │
  │  .cache_metadata.json  │
  └────────────┬───────────┘
               │
         ┌─────▼──────────┐
         │  AWS S3         │
         │  hr-documents-1 │
         │  executive/     │
         │  employee/      │
         │  master/        │
         └─────────────────┘
```

**Key flow:**
1. User authenticates via OAuth (Google/Azure AD) or header-based dev login.
2. Role derived from email → `EXECUTIVE_EMAILS` or `EMPLOYEE_EMAILS`.
3. `HrBot` crew initialized with role-specific S3 documents.
4. Query goes through production guards (length, PII, content safety, prompt injection).
5. Semantic cache checked first (fuzzy keyword matching, 60–75% threshold).
6. If cache miss, CrewAI agent orchestrates tool calls (Hybrid RAG, Master Actions).
7. Response validated, sources appended, cached, and returned.

---

## 4. Core Components

### 4.1 `crew.py` — HrBot Class (1408 lines)

**Location:** `src/hr_bot/crew.py`

The central orchestration class. Key responsibilities:

- **Initialization:** Configures Amazon Bedrock LLM, loads role-specific S3 documents, builds RAG indexes, initializes semantic caching and long-term memory.
- **`query_with_cache()`** — Main entry point for queries:
  - Production guards: empty query, length limit (2500 chars), content safety, PII.
  - Checks semantic cache → returns instant if hit.
  - Handles small talk (greetings, thanks, farewells, identity questions) without invoking tools.
  - Executes CrewAI crew with retry logic (3 retries, exponential backoff for AWS rate limits).
  - Extracts token usage metadata for cost tracking.
  - Filters technical failure responses from cache.
- **`_check_content_safety()`** — Blocks profanity, explicit sexual content, violent/threatening language, hate speech. Exceptions for legitimate HR policy questions.
- **`_is_legitimate_hr_policy_question()`** — Detects serious workplace concerns (harassment, discrimination, blackmail, etc.) that should be answered via policy search, not blocked.
- **`_small_talk_response()`** — Returns canned responses for greetings, thanks, farewells, identity questions.
- **`CrewWithSources` (inner class)** — Wraps crew to:
  - Inject conversation memory context.
  - Clean agent reasoning leaks (Thought:/Action:/Observation: blocks).
  - Collect sources from both Hybrid RAG and Master Actions tools.
  - Suppress sources for safety/ethical responses and "no info found" answers.
  - Persist conversation snippets to long-term memory.
  - Retry on empty LLM responses (up to 2 retries).
- **`remove_document_evidence_section()`** — Strips source/evidence blocks from responses.
- **`validate_response_against_sources()`** — Anti-hallucination guard: checks if response is grounded in retrieved documents.
- **Class-level RAG cache (`_rag_tool_cache`)** — Shared across instances to avoid rebuilding indexes for the same role.
- **Long-term memory** — SQLite via CrewAI's `LTMSQLiteStorage`, stored in `storage/long_term_memory.db`.
- **Bedrock embedder config** — Amazon Titan Embed Text for crew-level memory.

### 4.2 `main.py` — CLI Entry Points (240 lines)

**Location:** `src/hr_bot/main.py`

- `run()` / `run_crew()` — Single query execution.
- `interactive()` — Interactive REPL mode.
- `setup()` — Environment verification (data dir, env vars, config summary).
- `train()` — CrewAI training for fine-tuning.

### 4.3 Agent Configuration (`agents.yaml`, 172 lines)

**Location:** `src/hr_bot/config/agents.yaml`

Defines the `general_assistant` agent with:
- **Role:** "Inara - Your Friendly AI Knowledge Assistant & Expert Advisor"
- **Goal:** Hybrid document + general knowledge responses.
- **Backstory:** Extensive prompt engineering covering:
  - Hybrid response approach (documents + general knowledge combined).
  - Naming clarification (Inara = assistant, not company).
  - Security & input validation (prompt injection defense, query length, PII protection, source authenticity).
  - Human touch principles (conversational, empathetic, professional).
  - Special query types (capability questions, greetings, thanks).
  - When to use tools vs direct response.

### 4.4 Task Configuration (`tasks.yaml`, 161 lines)

**Location:** `src/hr_bot/config/tasks.yaml`

Defines the `answer_query` task with:
- Security validation (length, injection, PII) as first step.
- Query classification (hybrid / document-only / general knowledge).
- Tool selection logic (master_actions_guide vs document_search, one tool at a time).
- Response quality requirements (warm opening, detailed answer, action steps, what happens next, tips, closing, sources).
- India-specific requirement for general knowledge (Indian laws, ₹ INR, government bodies).
- Anti-hallucination protocol (verbatim accuracy, numbers are sacred, clearly separate document vs general knowledge).
- Formatting requirements (bold, numbered lists, bullet points, 200+ word minimum).

### 4.5 Settings (`settings.py`)

**Location:** `src/hr_bot/config/settings.py`

Pydantic-based settings with env var support:

| Setting | Default | Description |
|---------|---------|-------------|
| `chunk_size` | 800 | Document chunk size in chars |
| `chunk_overlap` | 200 | Overlap between chunks |
| `top_k_results` | 12 | Number of RAG results |
| `bm25_weight` | 0.5 | BM25 search weight |
| `vector_weight` | 0.5 | Vector search weight |
| `rrf_multiplier` | 12 | RRF candidate multiplier |
| `rrf_bm25_weight` | 1.5 | RRF BM25 weight |
| `rrf_vector_weight` | 1.0 | RRF vector weight |
| `embedding_model` | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model |
| `embedding_dimension` | 384 | Embedding dimension |
| `enable_cache` | true | Enable caching |
| `cache_ttl` | 3600 | Cache TTL in seconds |

---

## 5. Tools

### 5.1 HybridRAGTool (`hybrid_rag_tool.py`, 1032 lines)

**Location:** `src/hr_bot/tools/hybrid_rag_tool.py`

CrewAI `BaseTool` wrapping the `HybridRAGRetriever`:

- **Document loading:** From local directory or S3 document paths (`.docx` via `Docx2txtLoader`).
- **Document classification:** Each document gets category, tags, priority, access level, keywords via `DocumentClassifier`.
- **Placeholder sanitization:** Replaces `[insert X]`, `[the Company]`, etc. with friendly text.
- **Chunking:** `RecursiveCharacterTextSplitter` with table-aware separators (`\n\n\n`, `\n\n`, `\n`, `. `).
- **Indexing:** FAISS vector store + BM25Okapi.
- **Hybrid search:** Reciprocal Rank Fusion (RRF) combining BM25 and vector scores with configurable weights.
- **Optional cross-encoder reranking:** `cross-encoder/ms-marco-MiniLM-L-6-v2` (CPU-friendly, opt-in via `RERANK_ENABLED`).
- **Index persistence:** FAISS saved/loaded from `.rag_index/`, BM25 pickled to `.rag_cache/`. 24-hour TTL.
- **S3 version-aware cache keys:** Index hash includes S3 ETag version hash for deterministic invalidation.
- **Category-based filtering:** `ENABLE_CATEGORY_FILTERING` env var to restrict results to relevant document categories.

### 5.2 MasterActionsTool (`master_actions_tool.py`, 616 lines)

**Location:** `src/hr_bot/tools/master_actions_tool.py`

Handles "How do I…?" procedural queries:

- Searches a dedicated Master Document (found by keywords: `knowledge`, `action`, `master`, `guide` in filename).
- Same hybrid RAG architecture (BM25 + FAISS) but tuned for action content:
  - Smaller chunks (600 chars, 150 overlap).
  - Higher BM25 weight (0.6) for keyword matching of action names.
- Query expansion with action-related synonyms (e.g., `apply` → `request, submit, file`).
- Confidence threshold filtering (`MASTER_ACTIONS_CONFIDENCE_THRESHOLD`, default 0.3).
- Returns `NO_ACTION_FOUND` if no relevant actions found.
- Index stored at `~/.master_actions_index/`.

### 5.3 APIDeckhHRTool (`apideck_hr_tool.py`, 598 lines)

**Location:** `src/hr_bot/tools/apideck_hr_tool.py`

Full CRUD integration with HR systems (Okta HRMS) via Apideck unified API:

- **Companies:** list, get, create, update, delete.
- **Departments:** list, get, create, update, delete.
- **Employees:** list, get, create, update, delete.
- **Payroll:** list, get, employee payroll history.
- **Schedules:** list employee schedules.
- **Time Off:** list, get, create, update, delete requests.
- 30-minute cache TTL for GET requests.
- Env vars: `APIDECK_API_KEY`, `APIDECK_APP_ID`, `APIDECK_SERVICE_ID`, `APIDECK_CONSUMER_ID`.

### 5.4 CustomTool (`custom_tool.py`)

Placeholder/template tool for extending the system.

### 5.5 Document Classifier (`document_classifier.py`, 225 lines)

**Location:** `src/hr_bot/utils/document_classifier.py`

Classifies documents into categories: Leave, Benefits, Conduct, Compensation, Working Conditions, Termination, Data Protection, Recruitment, Executive, General.

Extracts metadata:
- **Category** — Based on keyword scoring (filename gets 3x weight).
- **Tags** — Policy, guideline, procedure, form, annual, CSP, notification, etc.
- **Priority** — 1 (high: policy/mandatory), 2 (medium: guideline/procedure), 3 (low: form/template).
- **Access level** — Executive, employee, or all.
- **Keywords** — Extracted from content for retrieval enhancement.

---

## 6. UI Layer

### 6.1 Chainlit App (`chainlit_app.py`, 690 lines)

**Location:** `src/hr_bot/ui/chainlit_app.py`

Production front-end built on Chainlit:

- **OAuth callback** — Extracts email, derives role, rejects unauthorized users.
- **Header-based auth** — Dev/proxy login via `X-Forwarded-Email`, `X-Dev-Email`, `X-User-Email` headers (when `ALLOW_DEV_LOGIN=true`).
- **Bot initialization** — Lazy-loaded per role, cached in `BOT_CACHE` dict. Thread-safe with asyncio locks.
- **Warm-up** — Pre-runs 10 warmup queries on first use per role to cache embeddings, build indexes.
- **Action buttons:**
  - **Refresh S3 Docs** — Clears S3 cache, re-downloads, rebuilds RAG index.
  - **Clear Response Cache** — Purges semantic response cache.
  - **Admin Console** — Link to `/admin/` (admin users only).
- **Message handling:**
  - Progress messages ("Analyzing your request...").
  - History context injection (last 2–3 turns).
  - Augmented question construction with conversation history.
  - Format answer: clean markdown, remove document evidence, format sources as `Source1.docx · Source2.docx`.
  - Query logging to `data/logs/queries.jsonl` with timestamp, user, cached status, duration, tokens, cost.
- **Token estimation** — Heuristic: ~4 chars per token.
- **ThreadPoolExecutor** — `CHAINLIT_MAX_WORKERS` workers (default 4) for blocking operations.

### 6.2 Chainlit Markdown Files

- `chainlit.md` / `chainlit_en-GB.md` / `chainlit_en-IN.md` — Welcome message displayed in Chainlit UI. Describes RBAC, secure retrieval, admin actions, source citations.

### 6.3 Legacy Streamlit App (`app.py`)

**Location:** `src/hr_bot/ui/app.py`

Retained for emergency rollback only. Not installed by default (requires `uv sync --extra legacy`).

---

## 7. Admin Console

**Location:** `src/hr_bot/ui/admin/`  
**URL:** `/admin/`  
**Access:** Restricted to emails in `ADMIN_EMAILS` env var.  
**Tech:** Starlette routes + Jinja2 templates + HTMX (no React/heavy JS).

### Pages

| Page | Route | Description |
|------|-------|-------------|
| Dashboard | `/admin/` | Queries today, cache hit rate, indexed documents, active users, recent activity |
| Cache | `/admin/cache` | View cached responses, clear cache, hit rates, disk/memory size |
| Logs | `/admin/logs` | Query logs with user/source/search filters, admin audit log |
| Users | `/admin/users` | Configured employees, executives, admins |
| RAG | `/admin/rag` | Index status, document counts per role, rebuild/refresh actions |
| Settings | `/admin/settings` | Configuration overview (non-sensitive values) |

### Authentication (`auth.py`)

- Decodes Chainlit JWT (`access_token` cookie) using `CHAINLIT_AUTH_SECRET`.
- Extracts email from JWT payload (tries `email`, `sub`, `identifier`, nested `user` object).
- Checks against `ADMIN_EMAILS` for admin access.
- Returns `RedirectResponse` to main app if unauthorized.

### Services (`services.py`, 522 lines)

Backend logic for admin pages:

- **Dashboard stats** — Queries today, cache hit rate, user counts, document counts, RAG status.
- **Cache stats** — Read from `storage/response_cache/cache_stats.json`.
- **RAG stats** — Index file count, size, last rebuild time.
- **Query stats** — Parsed from `data/logs/queries.jsonl`.
- **Query logs** — Parsed JSONL with user/source/search filtering.
- **Admin audit log** — From `data/logs/admin_audit.jsonl`.
- **User management** — Reads `EXECUTIVE_EMAILS`, `EMPLOYEE_EMAILS`, `ADMIN_EMAILS`.
- **Document stats** — Counts cached docs per role from `/tmp/hr_bot_s3_cache/{role}/`.

---

## 8. S3 Document Management & Caching

### 8.1 S3DocumentLoader (`s3_loader.py`, 609 lines)

**Location:** `src/hr_bot/utils/s3_loader.py`

Role-based document loading from AWS S3 with intelligent caching:

**Role-based access:**
- **Executive:** `executive/` + `employee/` + `master/` prefixes.
- **Employee:** `employee/` + `master/` prefixes.

**S3 Configuration:**
- Bucket: `hr-documents-1` (env: `S3_BUCKET_NAME`)
- Region: `ap-south-1` (env: `S3_BUCKET_REGION`)
- Prefixes: `S3_EXECUTIVE_PREFIX`, `S3_EMPLOYEE_PREFIX`, `S3_MASTER_PREFIX`

**ETag-Based Smart Caching:**

1. **Cache validation flow:**
   - Check manifest exists → Check version file → Validate TTL (24h default) → Verify all cached files exist → Compare stored S3 version hash with current S3 ETags.
2. **Fast path (cache valid + S3 unchanged):** Load from local cache (<1s).
3. **Slow path (cache invalid or S3 changed):** Download from S3 (8–12s).
4. **Version hash:** SHA256 of all S3 object ETags (sorted, deterministic).

**Cache files (per role):**
- `/tmp/hr_bot_s3_cache/{role}/.cache_manifest` — List of cached file paths.
- `/tmp/hr_bot_s3_cache/{role}/.s3_version` — SHA256 hash of ETags.
- `/tmp/hr_bot_s3_cache/{role}/.cache_metadata.json` — Document metadata (size, last_modified, etag).

**Duplicate document handling:** Canonical path comparison to avoid indexing the same document twice when it appears under multiple S3 prefixes.

**Cache invalidation on S3 change:** Clears `.rag_cache`, `.rag_index`, `storage/response_cache`, and in-memory RAG tool cache to force complete rebuild.

### 8.2 Cost Comparison

| Approach | Annual Cost | Notes |
|----------|------------|-------|
| Short TTL (1h) | ~$180 | 720 GET/day per role |
| ETag-based (current) | ~$12 | 1 LIST/day + changes only |
| **Savings** | **~$168/year** | **93% reduction** |

---

## 9. Hybrid RAG System

### Architecture

```
Query
  ↓
BM25 Lexical Search ──→ Top-K candidates (weighted by rrf_bm25_weight=1.5)
  +
Vector Semantic Search ──→ Top-K candidates (weighted by rrf_vector_weight=1.0)
  ↓
Reciprocal Rank Fusion (RRF)
  ↓
Optional Cross-Encoder Reranking (ms-marco-MiniLM-L-6-v2)
  ↓
Top-K results (default: 12)
```

### Configuration

| Parameter | Default | Env Var | Description |
|-----------|---------|---------|-------------|
| Chunk size | 700 | `CHUNK_SIZE` | Characters per chunk |
| Chunk overlap | 200 | `CHUNK_OVERLAP` | Overlap between chunks |
| Top K | 12 | `TOP_K` / `TOP_K_RESULTS` | Results to return |
| BM25 weight | 0.5 | `BM25_WEIGHT` | BM25 contribution to ensemble |
| Vector weight | 0.5 | `VECTOR_WEIGHT` | Vector contribution to ensemble |
| RRF multiplier | 12 | `RRF_CANDIDATE_MULTIPLIER` | Candidate pool multiplier |
| RRF BM25 weight | 1.5 | `RRF_BM25_WEIGHT` | RRF BM25 contribution |
| RRF vector weight | 1.0 | `RRF_VECTOR_WEIGHT` | RRF vector contribution |
| Rerank enabled | true | `RERANK_ENABLED` | Enable cross-encoder reranking |
| Rerank top N | 50 | `RERANK_TOP_N` | Candidates to rerank |
| Reranker model | `cross-encoder/ms-marco-MiniLM-L-6-v2` | `RERANKER_MODEL` | Reranker model |
| Category filtering | true | `ENABLE_CATEGORY_FILTERING` | Filter by document category |

### Embeddings

- **Model:** `sentence-transformers/all-MiniLM-L6-v2`
- **Dimension:** 384
- **Runs on:** CPU (no GPU required)
- **Cost:** $0 (local inference)
- **Normalization:** Enabled (`normalize_embeddings=True`)

### Index Persistence

- **FAISS index:** `.rag_index/` directory.
- **BM25 index:** `.rag_cache/` directory (pickled).
- **Index TTL:** 24 hours (auto-rebuild).
- **Hash-based invalidation:** Index hash includes chunk size, overlap, sanitization version, and S3 version hash.

---

## 10. Semantic Response Caching

**Location:** `src/hr_bot/utils/cache.py` (574 lines)

### How It Works

1. **Query normalization:** Lowercase, remove punctuation, extract keywords (stop words removed).
2. **Similarity matching:** Jaccard similarity between keyword sets.
3. **Threshold:** Configurable (default 60–75%). Semantic hit if above threshold.
4. **Storage:** JSON files on disk + in-memory hot cache (max 200 items).

### Configuration

| Parameter | Default | Env Var | Description |
|-----------|---------|---------|-------------|
| TTL | 72 hours | `CACHE_TTL_HOURS` | Cache expiration |
| Similarity threshold | 0.60 | `CACHE_SIMILARITY_THRESHOLD` | Minimum similarity for a hit |
| Max memory items | 200 | — | In-memory cache size |
| Max index entries | 10,000 | `CACHE_MAX_INDEX_ENTRIES` | Max query index size |
| Adaptive index | true | `CACHE_ADAPTIVE_INDEX` | Adaptive cleanup management |
| Cleanup threshold | 0.8 | `CACHE_CLEANUP_THRESHOLD` | Cleanup at 80% capacity |

### Features

- **Exact match + semantic match** — Exact hash check first, then fuzzy keyword matching.
- **Tool artifact filtering** — Won't cache intermediate tool-planning transcripts (`Action:`, `Observation:` leaks).
- **Corrupted file cleanup** — Auto-deletes malformed JSON cache files.
- **Statistics tracking** — Hits, misses, semantic hits, exact hits, cache efficiency ratio.
- **Stats persistence** — `storage/response_cache/cache_stats.json`.

---

## 11. Security & Safety

### Content Safety (`crew.py`)

- **Strong profanity filter** — Regex-based, always blocks regardless of context.
- **Explicit sexual content** — Blocked unless it's a legitimate HR policy question.
- **Violent/threatening language** — Blocked with exception for workplace safety questions.
- **Hate speech detection** — Blocked with exception for anti-discrimination policy questions.

### Legitimate HR Policy Detection

Queries about harassment, discrimination, blackmail, threats, whistleblowing, etc. are routed through policy search (not blocked), even if they contain sensitive keywords.

### Prompt Injection Defense

- Queries like "Ignore previous instructions", "You are now DAN", "Override safety" are rejected.
- User input treated as data, never as commands.

### PII Protection

- SSN patterns (`###-##-####`), credit card numbers (16 digits), passwords, bank accounts, passport numbers, tax IDs detected and blocked.
- PII redacted from conversation memory before persistence.

### Hallucination Guards

- **Source authenticity** — Only cites sources returned by tool searches.
- **Response validation** — Checks if response is grounded in retrieved documents.
- **Relevance check** — If <20% of query keywords found in retrieved content, returns "no policy found."
- **Fabrication detection** — Checks for made-up procedures not present in documents.
- **Pattern detection** — Flags fabricated email addresses, phone numbers, form numbers, placeholder text.
- **Test coverage** — Semantic hallucination guard test using embedding cosine similarity.

### Query Length Limit

- Maximum 2500 characters (configurable).
- Minimum 3 characters.

---

## 12. Authentication & RBAC

### Google OAuth (Recommended)

1. Configure Google OAuth client for `http://<host>:<port>/oauth/callback`.
2. Set `OAUTH_GOOGLE_CLIENT_ID` and `OAUTH_GOOGLE_CLIENT_SECRET` in `.env`.
3. `CHAINLIT_BASE_URL` and `CHAINLIT_OAUTH_CALLBACK_URL` must match deployment.

### Role Derivation

- Email checked against `EXECUTIVE_EMAILS` → role = executive.
- Email checked against `EMPLOYEE_EMAILS` → role = employee.
- Not in either list → rejected ("unauthorized").

### Dev / Header-Based Login

When `ALLOW_DEV_LOGIN=true`, headers accepted: `X-Forwarded-Email`, `X-Dev-Email`, `X-User-Email`.

### Admin Access

- `ADMIN_EMAILS` env var controls admin console access.
- Admin console (`/admin/`) validates Chainlit JWT cookie.
- Non-admin users redirected to main app.

### Environment Variables for Auth

```bash
EXECUTIVE_EMAILS=exec1@company.com,exec2@company.com
EMPLOYEE_EMAILS=emp1@company.com,emp2@company.com
ADMIN_EMAILS=admin@company.com,another-admin@company.com
CHAINLIT_AUTH_SECRET=your-secret-here
CHAINLIT_BASE_URL=http://localhost:8501
ALLOW_DEV_LOGIN=true  # Dev only
DEV_TEST_EMAIL=dev@company.com
```

---

## 13. Configuration Reference

### Required Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `AWS_ACCESS_KEY_ID` | AWS IAM access key | `AKIA...` |
| `AWS_SECRET_ACCESS_KEY` | AWS IAM secret key | `wJa...` |
| `AWS_REGION` | AWS region for Bedrock | `us-east-1` |
| `BEDROCK_MODEL` | Bedrock model ID | `us.amazon.nova-lite-v1:0` |
| `CHAINLIT_AUTH_SECRET` | Session signing secret | Run `chainlit create-secret` |

### S3 Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `S3_BUCKET_NAME` | `hr-documents-1` | S3 bucket name |
| `S3_BUCKET_REGION` | `ap-south-1` | S3 bucket region |
| `S3_EXECUTIVE_PREFIX` | `executive/` | Executive documents prefix |
| `S3_EMPLOYEE_PREFIX` | `employee/` | Employee documents prefix |
| `S3_MASTER_PREFIX` | `master/` | Master documents prefix |
| `S3_CACHE_DIR` | System temp dir | Local cache base directory |

### Bedrock Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `BEDROCK_MODEL` | `bedrock/amazon.nova-lite-v1:0` | LLM model |
| `BEDROCK_EMBED_MODEL` | `amazon.titan-embed-text-v2:0` | Embedding model for crew memory |
| `BEDROCK_EMBED_REGION` | `us-east-1` | Embedding model region |

### Optional — Gemini (Alternative LLM)

| Variable | Default | Description |
|----------|---------|-------------|
| `GOOGLE_API_KEY` | — | Google API key for Gemini |
| `GEMINI_MODEL` | `gemini/gemini-1.5-flash` | Gemini model name |

### Optional — Apideck (HR System Integration)

| Variable | Default | Description |
|----------|---------|-------------|
| `APIDECK_API_KEY` | — | Apideck API key |
| `APIDECK_APP_ID` | — | Apideck application ID |
| `APIDECK_SERVICE_ID` | `okta` | HR platform service ID |
| `APIDECK_CONSUMER_ID` | `test-consumer` | Consumer ID |

### Cache & Performance

| Variable | Default | Description |
|----------|---------|-------------|
| `CACHE_TTL_HOURS` | `72` | Response cache TTL (hours) |
| `CACHE_SIMILARITY_THRESHOLD` | `0.60` | Semantic cache similarity threshold |
| `ENABLE_CACHE` | `true` | Enable/disable caching |
| `CACHE_TTL` | `3600` | RAG cache TTL (seconds) |
| `CACHE_MAX_INDEX_ENTRIES` | `10000` | Max query index entries |

### RAG Tuning

| Variable | Default | Description |
|----------|---------|-------------|
| `CHUNK_SIZE` | `700` | Document chunk size |
| `CHUNK_OVERLAP` | `200` | Chunk overlap |
| `TOP_K` / `TOP_K_RESULTS` | `12` | Results to return |
| `BM25_WEIGHT` | `0.5` | BM25 search weight |
| `VECTOR_WEIGHT` | `0.5` | Vector search weight |
| `RRF_CANDIDATE_MULTIPLIER` | `12` | RRF candidate pool |
| `RRF_BM25_WEIGHT` | `1.5` | RRF BM25 weight |
| `RRF_VECTOR_WEIGHT` | `1.0` | RRF vector weight |
| `RERANK_ENABLED` | `1` | Enable cross-encoder reranking |
| `RERANK_TOP_N` | `50` | Candidates to rerank |
| `MASTER_ACTIONS_CONFIDENCE_THRESHOLD` | `0.3` | Master Actions minimum score |
| `ENABLE_CATEGORY_FILTERING` | `true` | Category-based document filtering |

### Application

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_NAME` | `Inara` | Application display name |
| `APP_DESCRIPTION` | `your intelligent assistant` | Description text |
| `SUPPORT_CONTACT_EMAIL` | `support@company.com` | Support email |
| `CHAINLIT_MAX_WORKERS` | `4` | Thread pool workers |
| `TOKEN_COST_PER_1K_INPUT` | `0` | Cost per 1K input tokens (USD) |
| `TOKEN_COST_PER_1K_OUTPUT` | `0` | Cost per 1K output tokens (USD) |

---

## 14. CLI Commands

| Command | Script Entry | Description |
|---------|-------------|-------------|
| `hr_bot` | `hr_bot.main:run` | Run single query |
| `hr_bot_interactive` | `hr_bot.main:interactive` | Interactive REPL mode |
| `hr_bot_setup` | `hr_bot.main:setup` | Verify setup and config |
| `run_crew` | `hr_bot.main:run_crew` | Run via CrewAI CLI |
| `train` | `hr_bot.main:train` | Train the crew |
| `replay` | `hr_bot.main:replay` | Replay task execution |
| `test` | `hr_bot.main:test` | Test crew with evaluation |
| `generate_eval` | `hr_bot.eval.generate_dataset:main` | Generate evaluation dataset |
| `eval` | `hr_bot.eval.run_eval:main` | Run evaluation |
| `ragas_eval` | `hr_bot.eval.ragas_eval:main` | Run RAGAS evaluation |
| `ragas_prod_eval` | `hr_bot.eval.ragas_production_eval:main` | Run production RAGAS eval |

**Running the Chainlit UI:**

```bash
uv run chainlit run src/hr_bot/ui/chainlit_app.py --host 0.0.0.0 --port 8501
```

---

## 15. API Reference

### HybridRAGTool

```python
from hr_bot.tools import HybridRAGTool

tool = HybridRAGTool(
    data_dir="data",          # Local directory (or None for S3 mode)
    document_paths=None,      # List of file paths (S3 mode)
    s3_version_hash=None      # S3 ETag version hash
)

result = tool._run("What is the maternity leave policy?")
```

**Parameters:** `data_dir`, `chunk_size`, `chunk_overlap`, `top_k`, `bm25_weight`, `vector_weight`

### MasterActionsTool

```python
from hr_bot.tools import MasterActionsTool

tool = MasterActionsTool(
    cache_dir="/tmp/hr_bot_s3_cache/employee",
    s3_version_hash="abc123..."
)

result = tool._run("How do I apply for leave?")
```

### APIDeckhHRTool

```python
from hr_bot.tools import APIDeckhHRTool

tool = APIDeckhHRTool()

# List employees
result = tool._run(action="list_employees")

# Get employee
result = tool._run(action="get_employee", resource_id="12345")

# Create time-off request
result = tool._run(
    action="create_time_off_request",
    data={"employee_id": "12345", "type": "vacation", "start_date": "2026-03-01"}
)
```

### HrBot Crew

```python
from hr_bot.crew import HrBot

bot = HrBot(user_role="employee", use_s3=True)

# With caching (recommended)
result = bot.query_with_cache("What is the sick leave policy?")

# Direct crew kickoff (no caching)
crew = bot.crew()
result = crew.kickoff(inputs={"query": "...", "context": ""})
```

### Response Formats

**Document search response:**
```
📚 Retrieved HR Information:

[1] From: Maternity-Policy.docx
Maternity leave is available for up to 12 weeks...

[2] From: Leave-Policy.docx
Additional leave benefits include...
```

**Employee data response (Apideck):**
```
👤 Employee Information:
Name: John Doe | Email: john.doe@company.com | Department: Engineering
```

---

## 16. Evaluation & Testing

### Test Suite (`tests/test_rag_agent.py`, 119 lines)

Three tests:

1. **`test_retriever_build_and_search`** — Builds index, searches "sick leave policy", verifies relevant results returned.
2. **`test_agent_answers_with_content`** — Full agent query, checks answer mentions "sick"/"statutory", response <30s.
3. **`test_agent_hallucination_guard`** — Semantic hallucination test:
   - Retrieves top-12 chunks for "sick leave policy."
   - Gets agent answer.
   - Splits answer into sentences.
   - Embeds each sentence and each chunk with `all-MiniLM-L6-v2`.
   - Checks cosine similarity: each sentence must have ≥0.55 similarity with at least one chunk OR ≥0.75 similarity with the query itself.

### Evaluation Tools

| Tool | Entry Point | Description |
|------|-------------|-------------|
| Dataset Generator | `hr_bot.eval.generate_dataset` | Generates eval dataset |
| Run Eval | `hr_bot.eval.run_eval` | Retriever doc recall@K + snippet similarity + agent answer quality |
| RAGAS Eval | `hr_bot.eval.ragas_eval` | RAGAS framework metrics |
| RAGAS Prod Eval | `hr_bot.eval.ragas_production_eval` | Production RAGAS evaluation |

### Eval Metrics (`run_eval.py`)

- **`retriever_doc_recall@k`** — Fraction of eval examples where the source document appears in top-K results.
- **`retriever_avg_snippet_sim`** — Average Jaccard similarity between top result and gold snippet.
- **`agent_avg_answer_snippet_sim`** — Average Jaccard similarity between full agent answer and gold snippet.

### Data Files

- `data/eval/eval_dataset.jsonl` — Evaluation dataset (question, source, gold_snippet).
- `data/eval/metrics.json` — Evaluation metrics output.
- `data/eval/ragas_like_metrics.json` — RAGAS-style metrics.
- `data/eval/ragas_like_results.json` — RAGAS-style per-example results.
- `data/eval/retrieval_logs.jsonl` — Retrieval logs.
- `data/eval/production/examples.csv` — Production eval examples.

---

## 17. Deployment

### Quick Start (Local)

```bash
# Clone
git clone https://github.com/ARYDESTROYER/HR_BOT_V1.git
cd HR_BOT_V1

# Install dependencies
uv sync

# Optional: CrewAI CLI helpers
crewai install

# Configure
cp .env.example .env
nano .env  # Add AWS credentials, emails, auth secrets

# Run
uv run chainlit run src/hr_bot/ui/chainlit_app.py --host 0.0.0.0 --port 8501
```

### Production (systemd)

**Unit file:** `deploy/chat-chainlit.service`

```ini
[Unit]
Description=Inara (Chainlit)
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/chat/app/HR_BOT_V1
EnvironmentFile=/home/chat/app/HR_BOT_V1/.env
Environment="CHAINLIT_ENV_FILE=/home/chat/app/HR_BOT_V1/.env"
Environment="CHAINLIT_APP_ROOT=/home/chat/app/HR_BOT_V1"
ExecStart=/home/chat/app/HR_BOT_V1/.venv/bin/chainlit run /home/chat/app/HR_BOT_V1/src/hr_bot/ui/chainlit_app.py --host 0.0.0.0 --port 8501
Restart=on-failure
User=chat
Group=chat

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now chat-chainlit.service
```

### Legacy Streamlit Rollback

```bash
sudo systemctl stop chat-chainlit.service
uv sync --extra legacy
uv run python -m streamlit run src/hr_bot/ui/app.py
```

---

## 18. Costs & Performance

### LLM Costs (Amazon Bedrock Nova Lite)

| Metric | Value |
|--------|-------|
| Input pricing | ~$0.06 / 1M tokens |
| Output pricing | ~$0.24 / 1M tokens |
| Cost per query | ~$0.0002 |
| With semantic caching (~30–40% hit rate) | ~$0.0001/query |
| 1000 queries/month (Nova Lite) | ~$0.12–$0.20 |
| 1000 queries/month (Nova Pro) | ~$1.50 |
| 1000 queries/month (GPT-4-class) | ~$12.00 |

### S3 Costs

| Approach | Annual Cost |
|----------|------------|
| Short TTL (1h) | ~$180 |
| ETag-based (current) | ~$12 |

### Latency

| Scenario | Time |
|----------|------|
| Cold start (first query, index build) | 8–12s |
| Warm cache + unchanged S3 | <1s retrieval |
| Typical interactive query | 3–5s end-to-end |
| Cached query (semantic match) | <100ms |

### Memory Usage

| Component | Estimate |
|-----------|----------|
| Index storage | ~100MB / 1000 docs |
| Cache storage | ~10MB / 1000 queries |
| Runtime memory | ~500MB |

---

## 19. Project Structure

```
HR_BOT_V1/
├── guide.md                          # This file
├── README.md                         # Main documentation
├── QUICKSTART.md                     # Quick start guide (v6.0)
├── API_REFERENCE.md                  # API documentation (664 lines)
├── RELEASE_NOTES_v6.0.md             # v6.0 release notes
├── RELEASE_NOTES_v7.md               # v7.0 release notes
├── S3_CACHE_IMPLEMENTATION.md        # S3 caching deep dive
├── pyproject.toml                    # Project config (version 7.1)
├── chainlit.md                       # Chainlit welcome page
├── chainlit_en-GB.md                 # UK English variant
├── chainlit_en-IN.md                 # Indian English variant
├── test_s3_cache.py                  # S3 cache tests
│
├── src/hr_bot/
│   ├── __init__.py                   # Empty
│   ├── crew.py                       # CrewAI orchestration (1408 lines)
│   ├── main.py                       # CLI entry points (240 lines)
│   │
│   ├── config/
│   │   ├── agents.yaml               # Agent definitions (172 lines)
│   │   ├── tasks.yaml                # Task definitions (161 lines)
│   │   └── settings.py               # Pydantic settings
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── hybrid_rag_tool.py        # Hybrid RAG tool (1032 lines)
│   │   ├── master_actions_tool.py    # Master Actions tool (616 lines)
│   │   ├── apideck_hr_tool.py        # Apideck HR integration (598 lines)
│   │   └── custom_tool.py            # Template tool
│   │
│   ├── ui/
│   │   ├── chainlit_app.py           # Production Chainlit UI (690 lines)
│   │   ├── app.py                    # Legacy Streamlit UI
│   │   ├── admin/
│   │   │   ├── __init__.py
│   │   │   ├── routes.py             # Admin page routes (365 lines)
│   │   │   ├── services.py           # Admin backend logic (522 lines)
│   │   │   ├── auth.py               # Admin JWT auth
│   │   │   ├── static/admin.css      # Admin styles
│   │   │   └── templates/            # Jinja2 templates
│   │   │       ├── base.html
│   │   │       ├── dashboard.html
│   │   │       ├── cache.html
│   │   │       ├── logs.html
│   │   │       ├── rag.html
│   │   │       ├── settings.html
│   │   │       └── users.html
│   │   └── assets/ui.css
│   │
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── cache.py                  # Semantic response cache (574 lines)
│   │   ├── s3_loader.py              # S3 document loader (609 lines)
│   │   └── document_classifier.py    # Document categorization (225 lines)
│   │
│   ├── eval/
│   │   ├── __init__.py
│   │   ├── generate_dataset.py       # Eval dataset generator
│   │   ├── run_eval.py               # Retriever + agent evaluation
│   │   ├── ragas_eval.py             # RAGAS evaluation
│   │   └── ragas_production_eval.py  # Production RAGAS eval
│   │
│   └── test_docs/                    # Internal documentation
│       ├── PROJECT_SUMMARY.md
│       ├── DEPLOYMENT_GUIDE_v3.2.md
│       ├── SECURITY_AUDIT_v3.2.md
│       └── ... (11 files)
│
├── data/
│   ├── eval/                         # Evaluation data
│   ├── logs/                         # Query + admin audit logs
│   ├── Executive-Only-Documents/     # Executive docs (local)
│   ├── Regular-Employee-Documents/   # Employee docs (local)
│   └── Master-Document/              # Master actions doc (local)
│
├── deploy/
│   └── chat-chainlit.service         # systemd unit file
│
├── knowledge/
│   └── user_preference.txt           # User preferences (CrewAI)
│
├── public/
│   ├── custom.css                    # Chainlit custom styles
│   └── avatars/                      # User avatars
│
├── scripts/
│   ├── sync_public_assets.py
│   └── test_conversation.py
│
├── storage/
│   └── response_cache/               # Semantic cache files
│
└── tests/
    └── test_rag_agent.py             # RAG + hallucination tests (119 lines)
```

---

## 20. Known Issues & Troubleshooting

### OAuth 401 / Login Loops

**Cause:** Email not in `EXECUTIVE_EMAILS`/`EMPLOYEE_EMAILS`, `CHAINLIT_AUTH_SECRET` mismatch, or session cookie invalidation after secret rotation.  
**Fix:** Check server logs for "OAuth login rejected" messages. Add email to allow-list or enable `ALLOW_DEV_LOGIN` for debugging.

### Translation Keys Render Raw Tokens

**Cause:** Translation bundle missing key or casing mismatch.  
**Fix:** Ensure `.chainlit/translations/` contains the expected keys.

### Index Build Fails or Slow

**Cause:** Insufficient disk space, permissions, or large documents overloading memory.  
**Fix:** Monitor disk/memory, reduce `CHUNK_SIZE`, prebuild indexes on a machine with more resources.

### Provider Selection Confusion

**Cause:** Multiple provider env vars set simultaneously (e.g., `BEDROCK_MODEL` and `OPENROUTER_API_KEY`).  
**Fix:** Only populate env vars for the intended provider.

### No Documents Found

```bash
ls -la data/
# Add documents
cp /path/to/policies/*.docx data/
```

### Indexes Not Updating

```bash
rm -rf .rag_index/ .rag_cache/
# Next run will rebuild
```

### Out of Memory

Reduce `CHUNK_SIZE` and `TOP_K_RESULTS` in `.env`.

### Empty LLM Responses

Built-in retry logic (2 retries with 1s delay). If persistent, check AWS Bedrock rate limits.

### Agent Reasoning Leaks

`_clean_agent_reasoning_leaks()` strips `Thought:`, `Action:`, `Observation:` blocks from responses. If leaks still appear, clear response cache.

---

## 21. Dependencies

### Core (`pyproject.toml`)

| Package | Version | Purpose |
|---------|---------|---------|
| `crewai[tools]` | ≥0.130.0, <1.0.0 | Agent orchestration |
| `langchain` | ≥0.3.0 | LLM framework |
| `langchain-community` | ≥0.3.0 | Community integrations |
| `langchain-core` | ≥0.3.0 | Core abstractions |
| `boto3` | ≥1.28.0 | AWS SDK |
| `langchain-aws` | ≥0.1.0 | AWS Bedrock integration |
| `faiss-cpu` | ≥1.8.0 | Vector store |
| `rank-bm25` | ≥0.2.2 | BM25 search |
| `unstructured[docx]` | ≥0.12.0 | Document processing |
| `python-docx` | ≥1.1.0 | DOCX handling |
| `docx2txt` | ≥0.8 | DOCX text extraction |
| `httpx` | ≥0.27.0 | HTTP client |
| `diskcache` | ≥5.6.3 | Disk-based caching |
| `pydantic` | ≥2.5.0 | Data validation |
| `pydantic-settings` | ≥2.1.0 | Settings management |
| `python-dotenv` | ≥1.0.0 | Env file loading |
| `langchain-huggingface` | ≥0.3.0 | HuggingFace embeddings |
| `sentence-transformers` | ==2.7.0 | Sentence embeddings |
| `torch` | ==2.6.0 | ML framework |
| `pytest` | ≥8.2.0 | Testing |
| `ragas` | ≥0.1.20 | RAG evaluation |
| `datasets` | ≥2.19.0 | Dataset handling |
| `evaluate` | ≥0.4.1 | Metrics |
| `fastapi` | ≥0.109.0 | API framework |
| `uvicorn[standard]` | ≥0.27.0 | ASGI server |
| `pyjwt[crypto]` | ≥2.8.0 | JWT handling |
| `jinja2` | ≥3.1.6 | Template engine |
| `chainlit` | ≥2.9.0 | Chat UI framework |
| `starlette` | ≥0.49.3 | ASGI toolkit |
| `authlib` | ≥1.6.5 | OAuth library |

### Optional

| Package | Extra | Purpose |
|---------|-------|---------|
| `streamlit` | `legacy` | Legacy UI rollback |

### Build System

- **Backend:** `hatchling`
- **CrewAI type:** `crew`

---

*End of guide. This document covers every aspect of the Inara HR Assistant v8.0 codebase as of 2026-02-21.*
