# Phase 6 Plan — Advanced Agent, Caching, Transforms, Ollama & Code Quality

> Status: **future** — depends on Phase 4 + Phase 5 completion

## Overview

Phase 6 addresses platform maturity: smarter agent capabilities, performance via caching,
extensible transform pipelines, and codebase maintainability. These are independent workstreams
that can be developed in parallel.

---

## 1. DuckDB JSON Flattening Skills

### Problem

The LLM struggles with DuckDB-specific JSON extraction syntax, especially:
- `json_extract(payload, '$.nested.field')` vs `payload->>'$.field'`
- `UNNEST` for array flattening (DuckDB-specific, not standard SQL)
- Struct access vs JSON access patterns
- Reversing: flat columns back into nested JSON for gold views

### Solution: Few-shot skill library

Add a structured skill library to the agent's system prompt, loaded dynamically based on context.

**New file:** `services/api/src/agent/skills/json_patterns.py`

```python
JSON_SKILLS = [
    {
        "name": "extract_flat_fields",
        "description": "Extract top-level JSON fields into typed columns",
        "pattern": """
-- Source: bronze table with `payload` JSON column
-- Target: silver table with flat typed columns
SELECT
    json_extract_string(payload, '$.id') AS id,
    CAST(json_extract(payload, '$.amount') AS DOUBLE) AS amount,
    CAST(json_extract_string(payload, '$.created_at') AS TIMESTAMP) AS created_at
FROM bronze.{source}
WHERE json_extract_string(payload, '$.id') IS NOT NULL
""",
    },
    {
        "name": "unnest_array",
        "description": "Flatten a JSON array into rows",
        "pattern": """
-- Source: bronze table with nested array in payload
-- Target: silver table with one row per array element
SELECT
    json_extract_string(payload, '$.parent_id') AS parent_id,
    UNNEST(from_json(json_extract(payload, '$.items'), '["JSON"]')) AS item_json
FROM bronze.{source}
""",
    },
    {
        "name": "struct_to_json",
        "description": "Re-aggregate flat columns back into JSON",
        "pattern": """
-- Gold view: re-nest related rows into JSON array
SELECT
    parent_id,
    to_json(list({col1: col1, col2: col2})) AS items_json
FROM silver.{source}
GROUP BY parent_id
""",
    },
]
```

**Injection strategy:**
- When the agent's tool-use loop detects a bronze entity with JSON payload columns, inject relevant skills into the system prompt
- Skills are templates with `{source}` / `{target}` placeholders the LLM fills in
- Include 2-3 concrete examples per skill (few-shot) — proven to improve DuckDB SQL accuracy

**No locking concern:** DuckDB's MVCC handles concurrent reads. Writes are single-writer but transforms already run sequentially via the task queue. No table-level locking needed.

---

## 2. Event-Driven vs Scheduled Transforms

### Problem

Currently transforms are manually triggered or (Phase 4) cron-scheduled. Neither handles:
- "Run silver transform when new bronze data lands"
- "Rebuild gold view when any of its 3 source silver tables change"
- Cross-table dependency chains

### Design: Hybrid trigger model

#### Option A: Change-driven triggers (recommended for v1)

Add a `trigger_mode` column to `transforms.transform`:

```sql
ALTER TABLE transforms.transform ADD COLUMN trigger_mode VARCHAR DEFAULT 'manual';
-- Values: 'manual' | 'schedule' | 'on_change'

ALTER TABLE transforms.transform ADD COLUMN watch_entities JSON;
-- Array of entity IDs to watch: ["entity-uuid-1", "entity-uuid-2"]
```

**Trigger mechanism:**
- After any successful data landing (webhook ingest, batch upload, connector pull, transform execution), emit an internal event: `data_changed(entity_id, tenant_id, row_count)`
- A lightweight event dispatcher checks `transforms.transform` for any transforms where `trigger_mode = 'on_change'` AND the changed entity is in `watch_entities`
- Matching transforms are queued for execution

**Implementation:**

**New file:** `services/api/src/transforms/triggers.py`
```python
async def on_data_changed(entity_id: str, tenant_id: str):
    """Find and queue transforms watching this entity."""
    # Query transforms with trigger_mode='on_change'
    # where entity_id is in watch_entities JSON array
    # Queue each for execution (avoid duplicate runs)
```

**Call sites — add `on_data_changed()` after:**
- `integrations/ingest.py` — after successful webhook/batch/api_pull landing
- `transforms/service.py` — after successful transform execution (cascading!)

**Cascade protection:**
- Max depth limit (default 5) to prevent infinite loops
- Cycle detection: track `execution_chain` in transform_run metadata
- Debounce: if a transform was triggered <30s ago, skip (configurable)

#### Option B: Full DAG scheduler (future)

For complex multi-step pipelines, consider a proper DAG engine:
- Build dependency graph from `entity_lineage` table
- Topological sort for execution order
- Parallel execution of independent branches
- Visual DAG editor in UI (extends LineagePage)

This is Phase 7+ territory — the simple event-driven model covers 90% of use cases.

#### Schedule vs Change: when to use which

| Pattern | Use Schedule | Use On-Change |
|---------|-------------|---------------|
| External API pull | Yes (cron) | No (external data, no internal event) |
| Bronze -> Silver cleaning | No | Yes (trigger on bronze ingest) |
| Silver -> Gold aggregation | Maybe (hourly) | Yes (trigger on silver update) |
| Cross-domain gold join | Maybe (daily) | Yes (trigger on any source change) |
| Heavy batch rebuild | Yes (nightly) | No (too expensive to run on every change) |

---

## 3. Cached API Layer (Redis/Cloudflare)

### Problem

Querying DuckDB directly for every API request doesn't scale. Silver and gold tables are read-heavy and change infrequently — perfect for caching.

### Architecture

```
Client -> API Gateway -> Cache Layer -> DuckDB
                            |
                     Redis (local dev)
                     Cloudflare KV (prod)
```

### Implementation

#### 3a. Cache middleware

**New file:** `services/api/src/cache/middleware.py`

```python
class CacheConfig:
    backend: Literal["redis", "memory", "cloudflare"]
    default_ttl: int = 300  # 5 min
    prefix: str = "jonas:"

class CacheLayer:
    async def get(self, key: str) -> Optional[bytes]: ...
    async def set(self, key: str, value: bytes, ttl: int): ...
    async def invalidate(self, pattern: str): ...
```

**Cache key structure:**
```
jonas:{tenant_id}:{layer}:{entity_name}:query:{hash(sql)}
jonas:{tenant_id}:{layer}:{entity_name}:preview:{page}
jonas:{tenant_id}:catalogue:entities
```

#### 3b. What to cache

| Endpoint | TTL | Invalidation trigger |
|----------|-----|---------------------|
| Entity preview (silver/gold) | 5 min | Transform execution on that entity |
| Catalogue entity list | 10 min | Entity create/update/delete |
| `run_sql` results (gold only) | 5 min | Transform execution on queried entities |
| Lineage graph | 30 min | Transform or entity create/delete |
| Dashboard stats | 2 min | Any mutation |

**Never cache:** Bronze data (too volatile), agent chat, audit logs.

#### 3c. GraphQL layer (optional, future)

Add a GraphQL endpoint for silver + gold data queries:

**New file:** `services/api/src/graphql/schema.py`

```python
# Auto-generate GraphQL types from catalogue entity_field definitions
# Only expose silver + gold layer entities
# Apply same RBAC + PII masking as REST endpoints
# Cache resolvers via the cache layer
```

**Stack:** `strawberry-graphql` (lightweight, async, FastAPI integration)

**Endpoint:** `POST /api/v1/graphql` — gated by same auth middleware

**Benefits:**
- Clients can query exactly the fields they need (reduces payload)
- Nested queries across related entities (joins via lineage)
- Subscriptions (future: real-time data updates via WebSocket)

**When to add:** Only if external consumers need flexible querying. The REST API + agent chat covers internal use well.

#### 3d. Infrastructure

**docker-compose.yml addition:**
```yaml
redis:
  image: redis:7-alpine
  ports: ["6379:6379"]
  volumes: [redis_data:/data]
```

**Environment:**
```
CACHE_BACKEND=redis        # or "memory" for dev without Redis
CACHE_REDIS_URL=redis://localhost:6379
CACHE_DEFAULT_TTL=300
```

---

## 4. Agent Memory & Context Injection

### Problem

The agent has no memory across sessions. It re-discovers the same patterns, forgets user preferences, and can't learn from past solutions.

### Design: Three-tier memory

#### Tier 1: Session memory (exists — chat history within a session)

Already implemented via client-side message array. Phase 4 adds server-side persistence in `audit.chat_session`.

#### Tier 2: Tenant memory (new — shared knowledge per tenant)

**New table:** `audit.agent_memory`
```sql
CREATE TABLE IF NOT EXISTS audit.agent_memory (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR NOT NULL,
    category VARCHAR NOT NULL,   -- 'routine' | 'solution' | 'preference' | 'context'
    summary VARCHAR NOT NULL,    -- human-readable description
    content JSON NOT NULL,       -- structured data (SQL patterns, entity references, etc.)
    relevance_score FLOAT DEFAULT 1.0,  -- decays over time, boosted on reuse
    created_by VARCHAR,
    created_at TIMESTAMP DEFAULT now(),
    last_used_at TIMESTAMP DEFAULT now(),
    use_count INTEGER DEFAULT 0
);
```

**Memory types:**

| Category | Example | How it's created |
|----------|---------|-----------------|
| `routine` | "Every Monday, refresh the weekly_sales gold view" | User tells agent, or agent observes repeated pattern |
| `solution` | "To flatten orders JSON, use UNNEST with from_json" | Agent saves after successfully helping user |
| `preference` | "User prefers snake_case column names" | Explicit user instruction |
| `context` | "The sensor_readings entity has invalid values >100 in the temperature column" | Agent discovers during data exploration |

**Injection into system prompt:**
```python
def _build_memory_context(tenant_id: str, user_message: str) -> str:
    # 1. Keyword match: extract entity names, column names from user message
    # 2. Query agent_memory for matching tenant memories
    # 3. Rank by relevance_score * recency
    # 4. Take top 5 memories
    # 5. Format as "## What I remember\n- ..."
    # 6. Inject into system prompt below catalogue context
```

**Memory lifecycle:**
- **Create:** Agent explicitly calls `save_memory` tool after solving a problem
- **Recall:** Automatic injection into system prompt based on relevance
- **Decay:** `relevance_score *= 0.95` daily for unused memories
- **Boost:** `relevance_score = min(2.0, score * 1.2)` when memory is used
- **Prune:** Delete memories with `relevance_score < 0.1` or unused for 90 days

**New agent tools:**
- `save_memory(category, summary, content)` — store a memory
- `recall_memories(query)` — explicitly search memories (beyond auto-injection)
- `forget_memory(memory_id)` — delete a specific memory

#### Tier 3: Global memory (future — cross-tenant patterns)

Anonymised patterns that work across tenants (e.g., "DuckDB JSON flattening works best with json_extract_string"). This is essentially the skills library from section 1, but learned rather than hardcoded.

---

## 5. Context Pruning & Compaction

### Problem

As conversations grow long, the full message history exceeds context windows. Tool call results (especially `run_sql` with large result sets) bloat the context.

### Design

#### 5a. Result truncation (immediate)

**File:** `services/api/src/agent/service.py`

Apply limits to tool results before adding to conversation:
```python
MAX_SQL_RESULT_ROWS = 20      # truncate with "... and N more rows"
MAX_PREVIEW_ROWS = 10
MAX_SCHEMA_FIELDS = 50        # summarise if entity has >50 fields
MAX_TOOL_RESULT_CHARS = 4000  # hard cap on any tool result
```

#### 5b. Conversation compaction (medium-term)

When conversation exceeds a token threshold (e.g., 80% of context window):

1. **Summarise older turns:** Send older messages to a fast/cheap model with: "Summarise this conversation so far in 200 words, preserving: entity names mentioned, SQL patterns used, decisions made, current goal."
2. **Replace history:** Replace messages 0..N with a single system message containing the summary
3. **Keep recent:** Always keep the last 6-8 messages verbatim

**Implementation:**
```python
def _compact_history(messages: list[dict], max_tokens: int) -> list[dict]:
    token_count = estimate_tokens(messages)
    if token_count < max_tokens * 0.8:
        return messages  # no compaction needed

    # Split: older messages to summarise, recent to keep
    split_point = len(messages) - 8
    older = messages[:split_point]
    recent = messages[split_point:]

    summary = llm_summarise(older)  # fast model call
    return [{"role": "system", "content": f"## Conversation summary\n{summary}"}] + recent
```

#### 5c. Selective tool result caching

Don't re-send full tool results in history. After a tool result is processed:
- Keep a 1-line summary: `"[run_sql: returned 42 rows from silver.orders]"`
- Store full result in a side-channel (Redis or in-memory) for re-retrieval if needed
- Agent can call `recall_result(tool_call_id)` to get the full result back

---

## 6. Transformation Plugins (Skill Creator)

### Problem

SQL-only transforms can't handle complex logic: ML feature engineering, custom parsing, external API enrichment. Python transforms are mentioned in the architecture but not implemented.

### Design: Containerised Python skills

#### 6a. Skill definition

A skill is a Python function with:
- Declared input (source entity + columns)
- Declared output (target entity + columns)
- Minimal dependencies (declared in a requirements list)
- Sandboxed execution (Docker container)

**New table:** `transforms.skill`
```sql
CREATE TABLE IF NOT EXISTS transforms.skill (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    description VARCHAR,
    source_code TEXT NOT NULL,          -- Python source
    requirements JSON DEFAULT '[]',     -- ["pandas==2.1", "phonenumbers"]
    input_schema JSON NOT NULL,         -- [{entity, columns}]
    output_schema JSON NOT NULL,        -- [{entity, columns}]
    container_image VARCHAR,            -- built image tag (null = not built yet)
    status VARCHAR DEFAULT 'draft',     -- draft | building | ready | failed
    created_by VARCHAR,
    created_at TIMESTAMP DEFAULT now()
);
```

#### 6b. Skill template

```python
# Every skill implements this interface
from jonas_sdk import SkillContext

def run(ctx: SkillContext) -> None:
    """
    ctx.read("bronze.orders")     -> pyarrow.Table
    ctx.write("silver.orders", table)
    ctx.log("Processed 100 rows")
    ctx.config                    -> dict (user-provided params)
    """
    df = ctx.read("bronze.orders").to_pandas()
    # ... custom logic ...
    ctx.write("silver.orders_cleaned", pa.Table.from_pandas(result))
```

#### 6c. Container build pipeline

```
User creates skill (via agent or UI)
        |
        v
Build step: Dockerfile generated
  FROM python:3.11-slim
  COPY requirements.txt .
  RUN pip install -r requirements.txt
  COPY skill.py /app/
  COPY jonas_sdk.py /app/
  CMD ["python", "/app/skill.py"]
        |
        v
Image tagged: jonas-skill-{skill_id}:latest
        |
        v
Execution: docker run --rm --network=none \
    -v /data/parquet:/data:ro \
    -e SKILL_CONFIG='{"source":"bronze.orders"}' \
    jonas-skill-{skill_id}
```

**Security constraints:**
- `--network=none`: no internet access during execution
- Read-only data mount (writes go to a temp volume, committed only on success)
- Memory + CPU limits via Docker resource constraints
- Execution timeout (default 5 min)
- No host filesystem access beyond mounted data

#### 6d. Agent-assisted skill creation

The agent can help users write skills:

1. User: "I need to parse phone numbers in the contacts table into E.164 format"
2. Agent: drafts a skill using `phonenumbers` library, declares deps
3. User reviews and approves
4. System builds container image
5. Skill becomes available as a transform type

**New agent tool:** `create_skill(name, description, source_code, requirements, input_schema, output_schema)`

---

## 7. Specialised Small Ollama Models

### Problem

The platform supports Ollama for local/offline inference, but small models (e.g. `qwen3:1.7b`) fail in specific, predictable ways:
- Tool calls omit required fields (e.g. `layer` in `register_entity`) — crashes the stream
- JSON schema constraints in tool definitions are ignored
- Complex multi-step reasoning (infer → register → create connector) breaks down mid-chain
- DuckDB-specific SQL syntax errors are more frequent
- Context window is small (~4–8k tokens) — full catalogue context exhausts it

A single general model is a poor fit for all agent tasks. The solution is a **model routing layer**: direct each task to the smallest model capable of doing it correctly.

### Design: Task-based model routing

**New config:** `services/api/src/agent/model_router.py`

```python
class TaskType(str, Enum):
    CHAT = "chat"           # general conversation, clarification
    SQL = "sql"             # NL-to-SQL generation
    SCHEMA = "schema"       # JSON/CSV schema inference
    SUMMARY = "summary"     # conversation compaction, result summarisation
    TOOL_USE = "tool_use"   # structured tool call with JSON output

# Per-provider routing table (configurable via env/tenant config)
MODEL_ROUTING: dict[str, dict[TaskType, str]] = {
    "ollama": {
        TaskType.CHAT:     "qwen3:1.7b",      # fast, good enough for conversation
        TaskType.SQL:      "sqlcoder:7b",      # fine-tuned for SQL generation
        TaskType.SCHEMA:   "qwen3:1.7b",       # lightweight JSON extraction
        TaskType.SUMMARY:  "qwen3:0.6b",       # smallest possible for summarisation
        TaskType.TOOL_USE: "qwen3:4b",         # larger model needed for reliable tool use
    },
    "openai": {
        TaskType.CHAT:     "gpt-4o-mini",
        TaskType.SQL:      "gpt-4o-mini",
        TaskType.SCHEMA:   "gpt-4o-mini",
        TaskType.SUMMARY:  "gpt-4o-mini",
        TaskType.TOOL_USE: "gpt-4o",
    },
    "google": {
        # all tasks: gemini-flash for cost, gemini-pro for tool use
        TaskType.TOOL_USE: "gemini-2.0-pro",
        "_default":        "gemini-2.0-flash",
    },
}
```

### Recommended Ollama models per task

| Task | Recommended model | Why |
|------|------------------|-----|
| General chat / clarification | `qwen3:1.7b` or `llama3.2:3b` | Fast response, conversational quality sufficient |
| NL-to-SQL (DuckDB) | `sqlcoder:7b` (Defog) | Fine-tuned on SQL, significantly fewer syntax errors |
| Tool use / structured JSON | `qwen3:4b` or `mistral:7b` | More reliably follows JSON schema, fewer missing fields |
| Schema inference from sample | `qwen3:1.7b` | Simple classification task, lightweight model fine |
| Conversation summarisation | `qwen3:0.6b` | Tiny model, summarisation is low-complexity |
| PII detection | `qwen3:0.6b` | Binary classification, no generation needed |

**Why sqlcoder for SQL:** Defog's SQLCoder is fine-tuned on text-to-SQL benchmarks and dramatically outperforms general models on DuckDB dialect. It knows `UNNEST`, `json_extract_string`, window functions, and `INSERT OR REPLACE` patterns that `qwen3:1.7b` consistently misses.

### Defensive tool input handling (immediate fix)

Small models don't reliably honour `required` in JSON schema. Until routing is in place, all `_run_tool` implementations must be defensive:

**Pattern to enforce across all tools in `service.py`:**
```python
# NEVER: tool_input["required_field"]  -- crashes on missing field
# ALWAYS: tool_input.get("field", default)  -- safe with small models

# For missing required fields with no sensible default, return error to agent:
if not tool_input.get("name"):
    return json.dumps({"error": "register_entity requires 'name'. Please provide it."})
```

**Audit all tools** (`register_entity`, `draft_transform`, `create_connector`, etc.) and replace bare `[]` access with `.get()` + validation. The error JSON is returned as the tool result — the agent sees it and can self-correct.

### Prompt adaptation for small models

Small models need simpler, more directive system prompts. When `LLM_MODEL` resolves to a known small model, switch to a compact prompt variant:

**New file:** `services/api/src/agent/prompt.py`
```python
def build_system_prompt(role: str, catalogue_context: str, model: str) -> str:
    if _is_small_model(model):
        return _compact_prompt(role, catalogue_context)  # <500 tokens
    return _full_prompt(role, catalogue_context)         # full guidance

def _is_small_model(model: str) -> bool:
    small = {"qwen3:0.6b", "qwen3:1.7b", "llama3.2:1b", "llama3.2:3b"}
    return any(s in model for s in small)
```

**Compact prompt principles:**
- Remove verbose examples — replace with 1 short example per tool
- State tool names explicitly upfront: "Available tools: infer_schema, register_entity, run_sql, ..."
- Use numbered steps instead of prose: "Step 1: call infer_schema. Step 2: call register_entity."
- Reduce catalogue context: include only entity names + layers, not full field lists
- Strict output format instruction: "Always respond with a tool call or a plain text message. Never mix both."

### Catalogue context trimming for small context windows

**New config:** trim catalogue context based on model's known context limit.

```python
CONTEXT_BUDGETS = {
    "qwen3:0.6b":  512,
    "qwen3:1.7b":  1024,
    "qwen3:4b":    2048,
    "default":     4000,
}

def build_catalogue_context(entities, model: str) -> str:
    budget = CONTEXT_BUDGETS.get(model, CONTEXT_BUDGETS["default"])
    # Include entity names + layers first (most important)
    # Add field details only if budget allows
    # Truncate with "... and N more entities" if needed
```

### Implementation steps

1. **Immediate (no routing):** Audit all `tool_input["x"]` accesses in `service.py` → replace with `.get()` + error returns
2. **Short-term:** Extract `prompt.py`, add `_is_small_model()` check, switch to compact prompt for small models
3. **Medium-term:** Implement `model_router.py`, thread `task_type` through the agent loop
4. **Long-term:** Pull `sqlcoder:7b` and benchmark against `qwen3` on the standard demo SQL queries; promote if accuracy is measurably better

---

## 8. Code Refactoring & Organisation

### Problem

Several files are growing large. The codebase needs restructuring for maintainability without breaking the LLM's ability to read and understand it (important for agent self-improvement).

### Principles

- **One concern per file, <300 lines each**
- **Flat imports** — avoid deep nesting that confuses LLM context
- **Index files** for re-exports — LLM can read `__init__.py` to understand module surface
- **Consistent naming** — `{domain}/{concern}.py` pattern

### Backend refactoring plan

#### Current structure (files >200 lines):

| File | Lines | Issue |
|------|-------|-------|
| `agent/service.py` | ~350 | LLM loop + prompt building + tool dispatch |
| `agent/tools.py` | ~300 | 13 tool definitions + implementations |
| `integrations/ingest.py` | ~250 | webhook + batch + api_pull in one file |
| `catalogue/service.py` | ~250 | CRUD + context building + preview |

#### Proposed splits:

```
services/api/src/
  agent/
    __init__.py          # re-exports: chat, stream_chat
    router.py            # unchanged
    service.py           # slim: just chat/stream_chat entry points
    prompt.py            # NEW: system prompt building, catalogue context injection
    loop.py              # NEW: tool-use loop logic (extract from service.py)
    tools/
      __init__.py        # TOOL_DEFINITIONS list, tool dispatch
      catalogue.py       # infer_schema, register_entity, preview_entity, describe_entity
      query.py           # run_sql
      transforms.py      # draft_transform, list_transforms, update_transform
      connectors.py      # list_connectors, create_connector, discover_api
      memory.py          # NEW: save_memory, recall_memories (Phase 6)
    skills/
      json_patterns.py   # NEW: DuckDB JSON few-shot examples
    inference.py         # unchanged
    pii.py               # unchanged
  catalogue/
    router.py            # unchanged
    service.py           # CRUD only
    context.py           # NEW: build_catalogue_context (extract from service.py)
    preview.py           # NEW: entity preview + pagination (extract from service.py)
    models.py            # unchanged
  integrations/
    router.py            # unchanged
    service.py           # unchanged
    ingest/
      __init__.py        # re-exports: land_webhook, land_batch, land_api_pull
      webhook.py         # webhook landing logic
      batch.py           # CSV/JSON batch landing
      api_pull.py        # HTTP pull logic
    models.py            # unchanged
  transforms/
    router.py            # unchanged
    service.py           # CRUD + execute
    triggers.py          # NEW: on_data_changed event dispatch
    validation.py        # NEW: SQL validation (extract from service.py)
    models.py            # unchanged
  cache/                 # NEW (section 3)
    middleware.py
    backends.py
  scheduler/             # already planned in Phase 4
    scheduler.py
```

### Frontend refactoring plan

```
apps/dashboard/src/
  components/
    layout/
      Sidebar.tsx        # extract from App.tsx
      Header.tsx         # extract from App.tsx (token selector, tenant badge)
    data/
      DataPager.tsx      # Phase 4 component
      DataGrid.tsx       # extract from CataloguePage
    forms/
      Dialog.tsx
      ConfirmDialog.tsx
      FormField.tsx
    display/
      Badge.tsx
      Skeleton.tsx
      Toast.tsx
    chat/
      MessageBubble.tsx  # extract from ChatPage
      ToolCallCard.tsx   # extract from ChatPage
      FormCard.tsx       # jonas-form renderer (Phase 4)
  hooks/
    usePermissions.ts    # move from lib/
    useToast.ts          # new
  lib/
    api.ts               # keep
    constants.ts         # new: shared constants (layer colors, status maps)
  pages/
    (each page imports from components/, much shorter)
```

### LLM-friendly conventions

To keep the codebase easy for the agent to read:
- Every module has a docstring explaining its purpose in 1-2 lines
- `__init__.py` files list all public exports (agent can scan these to understand the module)
- No circular imports — use dependency injection or event dispatch
- Constants and type definitions at the top of each file
- Prefer named exports over `from x import *`

---

## Implementation Sequence

These workstreams are largely independent and can be parallelised:

| Workstream | Depends on | Priority |
|-----------|-----------|----------|
| 1. JSON flattening skills | None | High (improves agent immediately) |
| 2. Event-driven transforms | Phase 4 (scheduler) | High |
| 3. Cache layer | Phase 5 (auth for proper cache keys) | Medium |
| 4. Agent memory | Phase 4 (chat persistence) | Medium |
| 5. Context pruning | None | Medium |
| 6. Skill creator | Phase 5 (tenant isolation for containers) | Low |
| 7. Ollama model routing | None | High for local dev |
| 8. Code refactoring | Should be done incrementally alongside other work | Ongoing |

Suggested order:
1. **Ollama defensive handling** (immediate — fix crashes today, no architecture needed)
2. JSON skills + context pruning + compact Ollama prompts (quick wins, no infra)
3. Event-driven transforms (extends Phase 4 scheduler)
4. Agent memory (extends Phase 4 chat persistence)
5. Code refactoring (do during 2-4, not as a separate phase)
6. Cache layer (after auth is in place)
7. Skill creator (most complex, needs container infra)

---

## Open Questions

1. **Memory search:** Keyword match vs embedding-based semantic search for memory retrieval? Start with keyword, upgrade to embeddings if recall quality is poor.
2. **Skill sandboxing:** Docker-in-Docker (if API runs in Docker) vs sidecar container approach? Consider using the host Docker socket with strict constraints.
3. **Cache invalidation:** Event-driven (precise but complex) vs TTL-only (simple but stale)? Recommend hybrid: TTL + explicit invalidation on known mutations.
4. **GraphQL adoption:** Is there a real consumer need, or is REST + agent chat sufficient? Defer until external API consumers exist.
5. **Context window budget:** How much of the context to allocate to memories vs catalogue vs conversation? Needs experimentation — start with 10% memory, 20% catalogue, 70% conversation.
6. **Transform DAG depth:** What's the maximum cascade depth before it becomes a footgun? Default 5, configurable per tenant.
7. **SQLCoder viability:** Does `sqlcoder:7b` support Ollama's tool-call format, or does it only output SQL text? May need a wrapper that parses SQL output into a `run_sql` tool call structure.
8. **Model routing config surface:** Per-tenant model overrides (some tenants want cloud, some local), or global only? Tenant config table is the natural place once Phase 5 is done.
9. **Fallback on tool call failure:** If a small model produces a malformed tool call, retry once with the larger `tool_use` model before returning an error to the user.
