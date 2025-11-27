## Inara HR Assistant v7.1 – Enterprise AI HR Assistant

Production-ready AI assistant for HR teams, powered by **CrewAI** and **Amazon Bedrock Nova Lite**, with **role-based S3 document access**, **ETag-based smart caching**, and a **modern Chainlit web UI**.

---

## 1. Overview

- **Audience:** Enterprise HR / IT teams
- **Primary Surface:** Chainlit web app (Streamlit kept only for rollback)
- **Core Capabilities:**
	- Role-aware HR policy Q&A (Executive vs Employee views)
	- "How do I…?" guided workflows via Master Actions
	- Hybrid RAG (BM25 + vector) over S3-hosted documents
	- Ultra-low-cost LLM via Amazon Bedrock Nova Lite
	- Admin Console for system monitoring and management

---

## 2. Key Features (v7.1)

### 2.1 Role-Based S3 Document Management

- **Separate views by role:**
	- Executives: Executive-Only + Regular Employee + Master documents
	- Employees: Regular Employee + Master documents only
- **S3 layout:**
	- Bucket: `hr-documents-1`
	- Region: `ap-south-1`
	- Prefixes: `executive/`, `employee/`
- **Zero local file management:** Documents are loaded directly from S3.

### 2.2 ETag-Based Smart S3 Caching

- Uses S3 **ETags** to detect changes without re-downloading.
- Typical behavior per role:
	- Cold start: 8–12s (downloads and indexes all docs once)
	- Warm runs: `< 1s` when documents unchanged (LIST-only check).
- **Cost model (per role):**
	- Short TTL design (rejected): ~$180/year
	- ETag design (current): ~$12/year
	- **Savings:** ~$168/year (~93% GET reduction).

### 2.3 Hybrid RAG Retrieval

- **BM25 lexical search:** precise matches on policy names and keywords.
- **Vector search:** HuggingFace `all-MiniLM-L6-v2` embeddings (local, $0 cost).
- **FAISS index:** ~400+ chunks indexed with on-disk persistence.
- **Weighted fusion:** balances lexical and semantic scores.
- **Validation:** score thresholds prevent low-confidence / noisy answers.

### 2.4 Master Actions (Procedural “How-To” Flows)

Pre-built, clickable workflows (with links) for:

- Apply for leave
- Download payslip
- View leave balance
- Update profile
- Enroll in training

Earlier releases improved intent precision by expanding `stop_words` (e.g., `day`, `today`, `work`), so onboarding questions don't incorrectly trigger the "Apply for Half-Day Leave" guide.

### 2.5 Chainlit Web UI

- Production-focused Chainlit front-end (Streamlit is legacy only).
- **Features:**
	- Google / Azure AD OAuth with role-based RBAC checks
	- Two primary admin buttons:
		- **Refresh S3 Docs** – clears S3 cache, re-downloads docs, rebuilds RAG index
		- **Clear Response Cache** – clears LLM response cache
	- Real-time agent status (Analyzing → Searching → Preparing)
	- Premium dark theme, responsive layout, and branding-friendly header.

### 2.6 v7.1-Specific Improvements

- **Message hardening:** `_author_as_string` ensures Chainlit messages never serialize `cl.User` objects (fixing “author must be a string”).
- **Production guards:** Added input validation to prevent empty/short queries and overly long queries (now configurable; default limit set to 2500 characters). This stops accidental tool misuse and prompt-injection style inputs.
- **Assistant vs Company naming fix:** Clarified backstory so the assistant name `Inara` is never used as the employer/company name; responses now say "your company" when referring to employer policies, while `Inara` remains the assistant's name.
- **S3 & cache improvements:** RAG cache keys now include S3 version hashes (ETag) to ensure deterministic cache invalidation when documents change.
- **Source handling:** Source matching made case-insensitive and more robust to prevent duplicate/partial matches when injecting sources into answers.
- **PII redaction & memory safeguards:** Improved PII detection and redaction in conversation memory to avoid storing SSNs, credit card numbers, and other sensitive identifiers.
- **Hybrid RAG fixes:** Fixed RAG chunk merging bug to prevent splitting semantically connected content across chunks, improving answer quality and citation accuracy.
- **Misc:** small UX and CI fixes, improved tests and evaluation dataset coverage.

### 2.7 v7.1 – Admin Console

New lightweight admin dashboard at `/admin/` for system monitoring:

- **Dashboard** – quick stats: queries today, cache hit rate, indexed documents
- **Cache Management** – view cached responses, clear cache, see hit rates
- **Query Logs** – recent queries with user, timestamp, and response source
- **User Management** – view configured users (employees, executives, admins)
- **RAG Index** – status, document counts, rebuild/refresh actions
- **Settings** – current configuration overview

Access is restricted to emails listed in `ADMIN_EMAILS`. The console uses HTMX for lightweight interactivity—no React or heavy JS frameworks.

```bash
# Add to .env
ADMIN_EMAILS=admin@company.com,another-admin@company.com
```

---

## 3. Architecture at a Glance

- **Client:** Chainlit UI (OAuth, role selection, admin actions).
- **Orchestrator:** CrewAI-based `HrBot` crew.
- **Retrieval:** `HybridRAGTool` combining BM25 + MiniLM embeddings + FAISS.
- **Storage:**
	- AWS S3 (`executive/`, `employee/` prefixes)
	- Local S3 cache under `/tmp/hr_bot_s3_cache/{role}/`
	- On-disk index and metadata files (`.cache_manifest`, `.s3_version`, `.cache_metadata.json`).

---

## 4. Costs & Performance

### 4.1 LLM Costs (Amazon Bedrock Nova Lite)

- **Pricing (approx):**
	- Input: ~$0.06 / 1M tokens
	- Output: ~$0.24 / 1M tokens
- **Typical query:**
	- Effective cost: ~`$0.0002` per query
	- With semantic caching (~30–40% hit rate): down to ~`$0.0001` per query.
- **Comparison (1000 queries/month):**
	- Nova Lite: ~$0.12–$0.20
	- Nova Pro: ~$1.50
	- GPT-4-class: ~$12.00

### 4.2 S3 Caching Costs

| Approach           | Annual Cost | Notes                         |
|-------------------|------------:|--------------------------------|
| Short TTL (1h)    |   ~$180     | 720 GET/day per role          |
| ETag-based        |   ~$12      | 1 LIST/day + changes only     |

### 4.3 Latency

- First query after cold start: ~8–12s (index build + downloads).
- Warm cache + unchanged S3: `< 1s` for retrieval.
- Typical interactive use: 3–5s end-to-end including LLM.

---

## 4.4 Gemini (Optional) & API Deck (Optional)

You can optionally swap the LLM stack or enable live HR system integration:

- **Gemini 1.5 Flash / Pro (optional):**

	```bash
	GEMINI_MODEL=gemini/gemini-1.5-flash    # Fast, low-cost
	# GEMINI_MODEL=gemini/gemini-1.5-pro   # Higher quality, higher cost
	```

- **API Deck HR integration (optional):**

	```bash
	# Get these from https://developers.apideck.com
	APIDECK_API_KEY=your_apideck_api_key_here
	APIDECK_APP_ID=your_apideck_app_id_here
	APIDECK_SERVICE_ID=your_hr_service_id_here
	```

When enabled, the APIDeck tool can surface live HR data (e.g., employees, time-off, payroll) on top of the S3 document RAG.

---

## 5. Prerequisites

- **Python:** 3.10–3.13
- **Package manager:** [`uv`](https://docs.astral.sh/uv/) (recommended)
- **AWS:**
	- Account with Amazon Bedrock enabled
	- S3 bucket for HR documents (e.g., `hr-documents-1`)
- (Optional) **HR system integration:** API Deck credentials

---

## 6. Quick Start (Local)

From your workstation:

```bash
# 1) Clone the repo
git clone https://github.com/saishshinde15/HR_BOT_V1.git
cd HR_BOT_V1

# 2) Install dependencies (creates .venv/ automatically)
uv sync

# 3) (Optional) Install CrewAI CLI helpers
crewai install

# 4) Start the Chainlit UI
uv run chainlit run src/hr_bot/ui/chainlit_app.py --host 0.0.0.0 --port 8501
```

The app will be available at `http://localhost:8501`.

---

## 7. Configuration

Create a `.env` in the repo root (or use your deploy environment) with at least:

```bash
# AWS / Bedrock
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1

BEDROCK_MODEL=us.amazon.nova-lite-v1:0
BEDROCK_EMBED_MODEL=amazon.titan-embed-text-v2:0
BEDROCK_EMBED_REGION=us-east-1

# S3 documents
S3_BUCKET_NAME=hr-documents-1
S3_BUCKET_REGION=ap-south-1
S3_EXECUTIVE_PREFIX=executive/
S3_EMPLOYEE_PREFIX=employee/

# Role-based access
EXECUTIVE_EMAILS=exec1@company.com,exec2@company.com
EMPLOYEE_EMAILS=emp1@company.com,emp2@company.com

# Chainlit auth / base URL
CHAINLIT_BASE_URL=http://localhost:8501
CHAINLIT_AUTH_SECRET=replace_me

# Optional dev login
ALLOW_DEV_LOGIN=true
DEV_TEST_EMAIL=dev@company.com
```

Additional useful env vars:

```bash
SUPPORT_CONTACT_EMAIL=hr-support@company.com
CHAINLIT_MAX_WORKERS=4
```

> The app will copy `GOOGLE_CLIENT_ID` → `OAUTH_GOOGLE_CLIENT_ID` (and secret) for backward compatibility. Prefer the `CHAINLIT_`-prefixed variables for new deployments.

---

## 8. Deploying with systemd (Production)

Example unit file (see `deploy/chat-chainlit.service`):

```ini
[Unit]
Description=Inara HR Assistant (Chainlit)
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/HR_BOT_V1
EnvironmentFile=/opt/HR_BOT_V1/.env
ExecStart=/opt/HR_BOT_V1/.venv/bin/chainlit run src/hr_bot/ui/chainlit_app.py --host 0.0.0.0 --port 8501
Restart=on-failure
User=chat
Group=chat

[Install]
WantedBy=multi-user.target
```

Reload and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now chat-chainlit.service
```

Rollback to legacy Streamlit (if ever needed):

```bash
sudo systemctl stop chat-chainlit.service
uv run python -m streamlit run src/hr_bot/ui/app.py
```

---

## 9. Authentication & RBAC

### 9.1 Google OAuth (Recommended)

1. Configure Google OAuth client for `http://<host>:<port>/oauth/callback`.
2. Set `OAUTH_GOOGLE_CLIENT_ID` and `OAUTH_GOOGLE_CLIENT_SECRET` in `.env`.
3. Ensure `CHAINLIT_BASE_URL` and `CHAINLIT_OAUTH_CALLBACK_URL` match your deployment.

### 9.2 Role Derivation

- On successful login, `chainlit_app.py` derives the user’s role from their email using `EXECUTIVE_EMAILS` and `EMPLOYEE_EMAILS` lists.
- Any email not in either allow-list is rejected with a clear message.

### 9.3 Dev / Header-Based Login

- When `ALLOW_DEV_LOGIN=true`, headers such as `X-Forwarded-Email`, `X-Dev-Email`, or `X-User-Email` are accepted as identity sources (useful behind internal proxies or in tests).

---

## 10. Admin Actions (From the UI)

- **Refresh S3 Docs**
	- Clears local S3 cache and cached indexes
	- Re-downloads documents per user role
	- Rebuilds BM25 + FAISS indexes

- **Clear Response Cache**
	- Clears semantic / response cache so answers are regenerated.

Both actions run asynchronously and report success/failure inside the chat.

---

## 11. Typical Usage

### 11.1 Example Queries

- “How do I apply for leave?”
- “What is the work-from-home policy?”
- “Download my payslip and explain the payroll rules.”
- “What is the phone usage policy?”
- “How many days of vacation do I get?”

### 11.2 Safety & Validation

- Explicit / NSFW or abusive content is blocked with a professional message.
- When no matching policy exists (e.g., “cryptocurrency policy”), the bot answers honestly (“no policy found”) and may suggest contacting HR.

---

## 12. Project Structure (High-Level)

```text
HR_BOT_V1/
├── src/hr_bot/
│   ├── crew.py               # CrewAI orchestration
│   ├── main.py               # CLI entry points
│   ├── ui/
│   │   ├── chainlit_app.py   # Main Chainlit app
│   │   └── admin/            # Admin console (v7.1)
│   │       ├── routes.py     # Starlette routes
│   │       ├── services.py   # Backend logic
│   │       ├── auth.py       # JWT auth helpers
│   │       └── templates/    # Jinja2 templates
│   ├── tools/
│   │   ├── hybrid_rag_tool.py
│   │   └── master_actions_tool.py
│   └── utils/
│       ├── s3_loader.py
│       └── cache.py
├── data/
│   └── logs/                 # Query logs (v7.1)
├── deploy/
│   └── chat-chainlit.service # Sample systemd unit
├── pyproject.toml
└── README.md
```

---

## 13. Architecture Diagram

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ HR Bot v7.1 Architecture                                                │
│ Role-Based S3 + ETag Smart Caching + Hybrid RAG + Chainlit UI          │
└──────────────────────────────────────────────────────────────────────────┘

User Query (Role: Executive/Employee)
		↓
	┌───────────────────────┐
	│     Chainlit UI      │
	│  OAuth + RBAC Guard  │
	│  Admin Actions (2x)  │
	│  - Refresh S3 Docs   │
	│  - Clear Resp Cache  │
	└──────────┬────────────┘
		   ↓
	┌──────────────────────┐          ┌───────────────────┐
	│      HR Bot          │          │  Admin Console    │
	│   (CrewAI crew)      │          │  /admin/ (v7.1)   │
	│  Nova Lite via       │          │  - Dashboard      │
	│  Amazon Bedrock      │          │  - Cache mgmt     │
	│  Semantic Caching    │          │  - Query logs     │
	└──────────┬───────────┘          │  - User mgmt      │
		   ↓                      └───────────────────┘
	┌──────────────────────┐
	│    Hybrid RAG Tool   │
	│  Role-Based Filters  │
	│  BM25 + Embeddings   │
	└──────────┬───────────┘
		   │
   ┌───────────────┼───────────────────────────────┐
   ↓               ↓                               ↓
┌───────────────┐ ┌──────────────────┐   ┌─────────────────┐
│  S3 Loader    │ │ Vector Search    │   │  BM25 Search    │
│ ETag Caching  │ │ (MiniLM-L6-v2)   │   │  (Lexical)      │
└───────┬───────┘ └────────┬─────────┘   └────────┬────────┘
	│                  │                      │
	└──────────┬───────┴──────────────────────┘
		   ↓
	     ┌───────────────┐
	     │   FAISS Index │
	     │   400+ chunks │
	     └───────┬───────┘
		     │
	┌────────────┴────────────┐
	│      Local S3 Cache     │
	│  /tmp/hr_bot_s3_cache/ │
	│  - .cache_manifest     │
	│  - .s3_version (ETag)  │
	│  - .cache_metadata.json│
	└────────────┬────────────┘
		     │
	     ┌───────▼────────┐
	     │  AWS S3        │
	     │  hr-documents-1│
	     │  executive/    │
	     │  employee/     │
	     └────────────────┘

Cache Validation Flow:
  LIST S3 (ETags only) → Compare hash →
    - MATCH: use local cache (< 1s)
    - MISMATCH: download changed docs and rebuild index
```

---

## 14. Development & Testing

Run tests (where available):

```bash
uv run pytest
```

Format and lint:

```bash
uv run black src/
uv run ruff check src/
```

Evaluate RAG / agent quality (optional, if you use the eval tools):

```bash
uv run python -m hr_bot.eval.generate_dataset
uv run python -m hr_bot.eval.run_eval
```

---

## 15. Support & License

- Issues: open a GitHub issue on this repository.
- Documentation references:
	- https://docs.crewai.com
	- https://docs.aws.amazon.com/bedrock/
	- https://docs.chainlit.io

Licensed under the **MIT License**.

Designed & coded to make complex HR workflows feel simple, fast, and safe for enterprise users.
