# 🔌 API Reference

## Tools API

### HybridRAGTool

**Description**: Hybrid search tool combining BM25 (lexical) and vector search (semantic) for HR documents.

#### Initialization

```python
from hr_bot.tools import HybridRAGTool

# Initialize with default settings
tool = HybridRAGTool(data_dir="data")

# Initialize with custom settings
tool = HybridRAGTool(
    data_dir="data",
    chunk_size=800,
    chunk_overlap=200,
    top_k=5,
    bm25_weight=0.5,
    vector_weight=0.5
)
```

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `data_dir` | str | "data" | Directory containing .docx documents |
| `chunk_size` | int | 800 | Size of document chunks in characters |
| `chunk_overlap` | int | 200 | Overlap between chunks |
| `top_k` | int | 5 | Number of results to return |
| `bm25_weight` | float | 0.5 | Weight for BM25 keyword search (0-1) |
| `vector_weight` | float | 0.5 | Weight for vector semantic search (0-1) |

#### Method: `_run(query: str) -> str`

Execute hybrid search on documents.

**Parameters:**
- `query` (str): The search query

**Returns:**
- str: Formatted results with document chunks and sources

**Example:**
```python
result = tool._run("What is the maternity leave policy?")
print(result)
```

#### How It Works

1. **Query Processing**: Tokenizes and prepares query
2. **BM25 Search**: Performs keyword-based search across all chunks
3. **Vector Search**: Performs semantic similarity search using Gemini embeddings
4. **Score Fusion**: Combines scores using weighted average
5. **Ranking**: Sorts results by combined score
6. **Caching**: Stores results for future identical queries

#### Optimization Tips

**For keyword-heavy queries** (exact terms, policy names):
```python
tool = HybridRAGTool(
    bm25_weight=0.7,
    vector_weight=0.3
)
```

**For semantic queries** (concepts, related topics):
```python
tool = HybridRAGTool(
    bm25_weight=0.3,
    vector_weight=0.7
)
```

**For large document sets**:
```python
tool = HybridRAGTool(
    chunk_size=1000,  # Larger chunks
    chunk_overlap=250,
    top_k=3  # Fewer results
)
```

---

### APIDeckhHRTool

**Description**: Unified HR platform integration via API Deck for accessing live HR system data.

#### Initialization

```python
from hr_bot.tools import APIDeckhHRTool

# Initialize with environment variables
tool = APIDeckhHRTool()

# Initialize with explicit credentials
tool = APIDeckhHRTool(
    api_key="your_api_key",
    app_id="your_app_id",
    service_id="your_service_id"
)
```

#### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `api_key` | str | from env | API Deck API key |
| `app_id` | str | from env | API Deck application ID |
| `service_id` | str | from env | HR platform service ID |
| `base_url` | str | https://unify.apideck.com | API Deck base URL |
| `cache_ttl` | int | 1800 | Cache TTL in seconds (30 min) |

#### Method: `_run(query_type: str, employee_id: str = None, filters: str = None) -> str`

Execute HR system query.

**Parameters:**
- `query_type` (str): Type of query
  - `"employee"`: Get specific employee details
  - `"employees_list"`: List all employees
  - `"department"`: Get department information
  - `"time_off"`: Get time-off requests
  - `"payroll"`: Get payroll information
  - `"benefits"`: Get benefits information

- `employee_id` (str, optional): Employee ID for specific queries
- `filters` (str, optional): JSON string with additional filters

**Returns:**
- str: Formatted results with HR data

**Examples:**

```python
# Get employee details
result = tool._run(
    query_type="employee",
    employee_id="12345"
)

# List employees with filters
result = tool._run(
    query_type="employees_list",
    filters='{"department": "Engineering"}'
)

# Get time-off requests
result = tool._run(
    query_type="time_off",
    employee_id="12345"
)

# Get department info
result = tool._run(
    query_type="department",
    filters='{"department_id": "dept_001"}'
)
```

#### Supported Query Types

##### 1. Employee Query
```python
tool._run(
    query_type="employee",
    employee_id="12345"
)
```

**Returns:**
- Name, email, employee ID
- Department, job title
- Employment type and status
- Start date, manager info

##### 2. Employees List
```python
tool._run(
    query_type="employees_list",
    filters='{"department": "Sales", "status": "active"}'
)
```

**Returns:**
- List of up to 20 employees
- Basic info for each employee

##### 3. Time Off Requests
```python
tool._run(
    query_type="time_off",
    employee_id="12345"
)
```

**Returns:**
- Request ID, type, status
- Start/end dates, duration
- Approval status

##### 4. Department Information
```python
tool._run(
    query_type="department",
    filters='{"department_id": "dept_001"}'
)
```

**Returns:**
- Department details and structure

##### 5. Payroll Information
```python
tool._run(
    query_type="payroll",
    employee_id="12345"
)
```

**Returns:**
- Payroll records and details

##### 6. Benefits Information
```python
tool._run(
    query_type="benefits",
    employee_id="12345"
)
```

**Returns:**
- Employee benefits enrollment and details

#### Error Handling

The tool returns user-friendly error messages:

```python
# Missing configuration
"❌ API Deck not configured. Please set environment variables..."

# Invalid query type
"❌ Unknown query type: invalid_type"

# API errors
"❌ HTTP 401: Unauthorized"
"❌ Request failed: Connection timeout"
```

#### Caching

Results are automatically cached for:
- **30 minutes default** (configurable via `cache_ttl`)
- **Per unique query** (query type + parameters)
- **Automatic invalidation** after TTL expires

Disable caching for specific queries:
```python
# Note: Not directly exposed, but handled internally
# Fresh data is fetched if cache expires
```

---

## Crew API

### HrBot Crew

**Description**: Main crew orchestrating the HR assistant agent and tasks.

#### Initialization

```python
from hr_bot.crew import HrBot

bot = HrBot()
```

#### Method: `crew() -> Crew`

Returns configured CrewAI Crew instance.

**Example:**
```python
bot = HrBot()
crew = bot.crew()

result = crew.kickoff(inputs={
    'query': 'What is the sick leave policy?',
    'context': ''
})
print(result)
```

#### Agent: `hr_assistant`

**Role**: Expert HR Assistant

**Capabilities**:
- Document search via HybridRAGTool
- HR system data access via APIDeckhHRTool
- Context-aware responses
- Source citation
- Professional communication

**LLM**: Gemini 1.5 Flash (configurable)

**Configuration**:
```python
Agent(
    role="Expert HR Assistant",
    llm=LLM(model="gemini/gemini-1.5-flash"),
    tools=[HybridRAGTool(), APIDeckhHRTool()],
    temperature=0.3,
    max_iter=5,
    memory=True
)
```

#### Task: `answer_hr_query`

**Description**: Answer HR queries using available tools

**Inputs**:
- `query` (str): The user's question
- `context` (str): Additional context (optional)

**Output**: Comprehensive, sourced answer

**Example:**
```python
result = crew.kickoff(inputs={
    'query': 'How many vacation days do employees get?',
    'context': 'For full-time employees in the US office'
})
```

---

## Environment Variables

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `GOOGLE_API_KEY` | Google API key for Gemini | `AIza...` |

### Optional - Model

| Variable | Description | Default |
|----------|-------------|---------|
| `GEMINI_MODEL` | Gemini model name | `gemini/gemini-1.5-flash` |

### Optional - API Deck

| Variable | Description | Example |
|----------|-------------|---------|
| `APIDECK_API_KEY` | API Deck API key | `sk_live_...` |
| `APIDECK_APP_ID` | API Deck app ID | `app_...` |
| `APIDECK_SERVICE_ID` | HR service ID | `zoho-people` |

### Optional - Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `ENABLE_CACHE` | Enable caching | `true` |
| `CACHE_TTL` | Cache TTL (seconds) | `3600` |
| `CHUNK_SIZE` | Document chunk size | `800` |
| `CHUNK_OVERLAP` | Chunk overlap | `200` |
| `TOP_K_RESULTS` | Results to return | `5` |
| `BM25_WEIGHT` | BM25 search weight | `0.5` |
| `VECTOR_WEIGHT` | Vector search weight | `0.5` |

---

## CLI Commands

### `hr_bot`

Run single query.

```bash
hr_bot "What is the maternity leave policy?"
```

**Or interactive:**
```bash
hr_bot
# Then enter query when prompted
```

### `hr_bot_interactive`

Run in interactive mode for multiple queries.

```bash
hr_bot_interactive
```

### `hr_bot_setup`

Verify setup and configuration.

```bash
hr_bot_setup
```

**Output:**
- Documents count
- Environment variables status
- Configuration summary

### `train`

Train the crew (for fine-tuning).

```bash
crewai train <n_iterations> <output_file>
```

### `replay`

Replay a previous task execution.

```bash
crewai replay <task_id>
```

### `test`

Test the crew with evaluation.

```bash
crewai test <n_iterations> <eval_llm>
```

---

## Response Formats

### Document Search Response

```
📚 **Retrieved HR Information:**

**[1] From: Maternity-Policy.docx**
Maternity leave is available for up to 12 weeks...
[Full content]

---

**[2] From: Leave-Policy.docx**
Additional leave benefits include...
[Full content]

---
```

### Employee Data Response

```
👤 **Employee Information:**

**Name:** John Doe
**Email:** john.doe@company.com
**Employee ID:** 12345
**Department:** Engineering
**Job Title:** Senior Software Engineer
**Employment Type:** Full-time
**Status:** Active
**Start Date:** 2020-01-15
**Manager:** Jane Smith
```

### Time-Off Response

```
🏖️ **Time-Off Requests (3 requests):**

**Request ID:** req_001
**Employee:** 12345
**Type:** Vacation
**Start Date:** 2025-12-20
**End Date:** 2025-12-31
**Status:** Approved
**Days:** 10

---
```

---

## Code Examples

### Basic Usage

```python
from hr_bot.crew import HrBot

# Initialize
bot = HrBot()

# Ask a question
result = bot.crew().kickoff(inputs={
    'query': 'What is the remote work policy?',
    'context': ''
})

print(result)
```

### Custom Configuration

```python
import os
from hr_bot.tools import HybridRAGTool, APIDeckhHRTool

# Set custom configuration
os.environ['CHUNK_SIZE'] = '1000'
os.environ['TOP_K_RESULTS'] = '10'
os.environ['BM25_WEIGHT'] = '0.7'

# Initialize tools
rag_tool = HybridRAGTool(data_dir="custom_data")
api_tool = APIDeckhHRTool()

# Use in crew (via HrBot)
bot = HrBot()
result = bot.crew().kickoff(inputs={
    'query': 'Your question here'
})
```

### Direct Tool Usage

```python
from hr_bot.tools import HybridRAGTool

# Initialize
tool = HybridRAGTool(data_dir="data")

# Search documents
result = tool._run("maternity leave policy")
print(result)
```

```python
from hr_bot.tools import APIDeckhHRTool

# Initialize
tool = APIDeckhHRTool()

# Get employee data
result = tool._run(
    query_type="employee",
    employee_id="12345"
)
print(result)
```

---

## Performance Considerations

### Caching Strategy

- **Document Search**: 1 hour TTL (policies don't change often)
- **HR System Data**: 30 minutes TTL (more dynamic)
- **Cache Key**: Based on query + parameters
- **Storage**: Disk-based (persistent across restarts)

### Memory Usage

- **Index Storage**: ~100MB for 1000 documents
- **Cache Storage**: ~10MB per 1000 queries
- **Runtime Memory**: ~500MB during operation

### Response Times

- **First query** (cold start): 3-5 seconds
- **Subsequent queries** (warm): <2 seconds
- **Cached queries**: <100ms

### Scaling Recommendations

- **Documents**: Up to 10,000 documents tested
- **Concurrent Users**: Deploy with gunicorn/uvicorn
- **API Rate Limits**: Respect provider limits (Gemini, API Deck)

---

## Advanced Topics

### Custom Document Loaders

Add support for PDF, TXT, or other formats:

```python
# In hybrid_rag_tool.py
from langchain_community.document_loaders import PyPDFLoader

def _load_documents(self) -> List[Document]:
    documents = []

    # Load .docx
    for file in self.data_dir.glob("*.docx"):
        loader = Docx2txtLoader(str(file))
        documents.extend(loader.load())

    # Load .pdf
    for file in self.data_dir.glob("*.pdf"):
        loader = PyPDFLoader(str(file))
        documents.extend(loader.load())

    return documents
```

### Custom Embeddings

Use different embedding models:

```python
# OpenAI embeddings
from langchain_openai import OpenAIEmbeddings

embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

# HuggingFace embeddings
from langchain_community.embeddings import HuggingFaceEmbeddings

embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)
```

### Monitoring and Logging

Add logging for debugging:

```python
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In tool methods
logger.info(f"Processing query: {query}")
logger.debug(f"Retrieved {len(results)} results")
```

---

**For more examples and use cases, check the QUICKSTART.md guide!**
