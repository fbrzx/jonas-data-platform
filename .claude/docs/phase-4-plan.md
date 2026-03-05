# Phase 4 Plan — API Discovery, Scheduling, Audit & Silver Transforms

## Overview

Phase 4 turns Jonas into a fully self-service data platform: users discover and connect external APIs through chat, schedule recurring pulls, inspect all system activity in an audit view, and refine raw bronze data into silver through guided, safe transforms.

---

## 1. Rename: Integrations → Connectors

Rename the `integrations` concept to **connectors** throughout the codebase to better reflect intent.

**Scope:**
- DB schema: rename `integrations.integration` table → `integrations.connector` (keep schema name, rename table)
- API: `/api/v1/integrations` → `/api/v1/connectors`
- Dashboard: `IntegrationsPage` → `ConnectorsPage`, sidebar label
- Agent tools: `list_integrations` → `list_connectors`, `create_integration` → `create_connector`, etc.
- Models, service, router files renamed accordingly

**Migration:** `ALTER TABLE integrations.integration RENAME TO connector` in a new DDL migration `db/002_rename_integrations.sql`.

---

## 2. API Discovery via Chat

### 2a. Agent-guided API connection flow

Extend the Jonas agent to guide users through a conversational (or form-assisted) API connection setup:

**Conversation steps:**
1. User describes the API they want to connect (URL, auth, method, body)
2. Jonas presents a structured form card in chat (visual editor — see 2b) or collects fields conversationally
3. Jonas calls `discover_api` tool: performs a single HTTP pull, returns raw response + inferred schema
4. Jonas calls `infer_schema` on the response, presents detected fields + PII flags
5. User confirms entity name and layer (always bronze for raw imports)
6. Jonas calls `register_entity` then `create_connector`

**New agent tool: `discover_api`**
```python
# services/api/src/agent/tools.py — new tool
{
  "name": "discover_api",
  "description": "Perform a single HTTP request to an external API and return the raw response for schema inference.",
  "input_schema": {
    "type": "object",
    "properties": {
      "url": {"type": "string"},
      "method": {"type": "string", "enum": ["GET", "POST", "PUT"], "default": "GET"},
      "headers": {"type": "object"},
      "body": {"type": "object", "description": "Request body for POST/PUT"},
      "json_path": {"type": "string", "description": "JSONPath to the array of records (e.g. '$.data.items')"}
    },
    "required": ["url"]
  }
}
```

**Implementation in `agent/service.py` `_run_tool`:**
- Use `httpx` (add to `pyproject.toml`) to make the HTTP call
- Respect `json_path` to extract the record array from nested responses
- Return first 5 records for schema inference, full count
- Validate URL is http/https, no internal/private IPs (SSRF protection)

**New connector config fields (stored in `config` JSON):**
```json
{
  "url": "https://api.example.com/data",
  "method": "POST",
  "headers": {"Authorization": "Bearer {{TOKEN}}"},
  "body": {"page": 1, "limit": 100},
  "json_path": "$.results",
  "pagination": {
    "type": "page",           // or "cursor" or "offset"
    "page_param": "page",
    "limit_param": "limit",
    "limit": 100
  }
}
```

### 2b. Visual form card in chat

For complex API setup, Jonas can emit a structured JSON block that the frontend renders as an inline form card rather than plain text.

**Protocol:** Agent wraps form spec in a special fence:
```
```jonas-form
{
  "type": "api_connector",
  "fields": [
    {"key": "url",     "label": "API URL",     "type": "text",   "required": true},
    {"key": "method",  "label": "Method",      "type": "select", "options": ["GET","POST"]},
    {"key": "headers", "label": "Headers",     "type": "kv",     "placeholder": "Authorization: Bearer ..."},
    {"key": "body",    "label": "Request Body","type": "json"},
    {"key": "json_path","label":"JSON Path",   "type": "text",   "placeholder": "$.data"}
  ],
  "submit_label": "Discover"
}
```
```

**Frontend (`ChatPage.tsx`):**
- Detect ` ```jonas-form ` blocks in assistant messages
- Render inline `<ConnectorFormCard>` component instead of code block
- On submit, post form values as a new user message: `"Here are the connection details: <JSON>"`
- Jonas then calls `discover_api` automatically

---

## 3. Job Scheduler (Cron Pulls)

### 3a. Scheduler backend

Add a scheduler process that runs alongside the FastAPI app.

**Stack:** APScheduler (add `apscheduler>=3.10` to `pyproject.toml`)

**New file: `services/api/src/scheduler/scheduler.py`**
```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = BackgroundScheduler()

def start_scheduler(app):
    """Load all active cron connectors and schedule them."""
    # Called from main.py lifespan
    _reload_jobs()
    scheduler.start()

def _reload_jobs():
    """Re-read connector table and sync APScheduler jobs."""
    # For each connector with cron_schedule != None and status == active:
    #   scheduler.add_job(run_connector_pull, CronTrigger.from_crontab(cron), id=connector_id, replace_existing=True)

def run_connector_pull(connector_id: str, tenant_id: str):
    """Execute an api_pull for a connector and record the run."""
    from src.integrations.ingest import land_api_pull
    # ... call land_api_pull, write integration_run record
```

**DB change:** Add `cron_schedule VARCHAR` column to `integrations.connector` (migration `db/003_cron_schedule.sql`):
```sql
ALTER TABLE integrations.connector ADD COLUMN cron_schedule VARCHAR;
```

**Lifespan hook in `main.py`:**
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    from src.scheduler.scheduler import start_scheduler
    start_scheduler(app)
    yield
    scheduler.shutdown()
```

**Job reload trigger:** Whenever a connector is created/updated with a `cron_schedule`, call `_reload_jobs()` to pick it up immediately without restart.

### 3b. Cron UI in ConnectorsPage

Add cron schedule field to the connector create/edit form:

- Text input: `"Cron schedule (e.g. 0 * * * *)"` with validation
- Helper link to cron syntax reference
- Show next-run time computed client-side (use `cronstrue` npm package for human-readable display)
- Display "next run: in 2h 15m" badge on connector card if `cron_schedule` is set

**New API endpoint:** `PATCH /api/v1/connectors/{id}` already exists — just add `cron_schedule` to `ConnectorUpdate` model.

---

## 4. Audit Dashboard Page

### 4a. Backend

**New router: `services/api/src/audit/router.py`**

Endpoints:
- `GET /api/v1/audit/logs` — query `audit.audit_log` with filters: `entity_type`, `action`, `user_id`, date range, pagination
- `GET /api/v1/audit/conversations` — list agent chat sessions (requires persisting conversations — see below)
- `GET /api/v1/audit/jobs` — query `integrations.integration_run` + `transforms.transform_run`, unified view
- `GET /api/v1/audit/jobs/{job_id}` — detail for a single run

**Chat session persistence:**
Currently, chat history lives only in the client. Add server-side persistence:
- New table `audit.chat_session` (`id`, `tenant_id`, `user_id`, `started_at`, `message_count`, `summary`)
- New table `audit.chat_message` (`id`, `session_id`, `role`, `content`, `tool_calls JSON`, `created_at`)
- Agent router creates/appends to session on each call
- `GET /api/v1/audit/conversations/{session_id}` returns full message thread

**Add to `db/003_audit_tables.sql`:**
```sql
CREATE TABLE IF NOT EXISTS audit.chat_session (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR NOT NULL,
    user_id VARCHAR NOT NULL,
    started_at TIMESTAMP DEFAULT now(),
    message_count INTEGER DEFAULT 0,
    summary VARCHAR
);

CREATE TABLE IF NOT EXISTS audit.chat_message (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id VARCHAR NOT NULL,
    role VARCHAR NOT NULL,
    content VARCHAR,
    tool_calls JSON,
    created_at TIMESTAMP DEFAULT now()
);
```

### 4b. AuditPage frontend

**New page: `apps/dashboard/src/pages/AuditPage.tsx`**

Three tabs:
1. **Jobs** — unified table of connector pulls + transform runs, columns: type, name, status (badge), started, duration, rows in/out, error. Click to expand error detail.
2. **Conversations** — list of chat sessions (user, date, message count, summary). Click to replay full conversation in a read-only thread viewer.
3. **Logs** — scrollable audit log table with filters for action, entity_type, user.

All three tabs use the pager component (see §5).

Add to sidebar in `App.tsx`: `{ path: '/audit', label: 'Audit', icon: <ClockIcon /> }`

---

## 5. Data Pager Component

A reusable paginated data table for exploring full datasets.

**New component: `apps/dashboard/src/components/DataPager.tsx`**

Props:
```typescript
interface DataPagerProps {
  fetchPage: (page: number, pageSize: number) => Promise<{ rows: Record<string, unknown>[]; total: number }>
  pageSize?: number   // default 50
  columns?: string[]  // if omitted, infer from first row
}
```

Features:
- Page controls: prev / next / page input / total row count display
- Column header sort (client-side for current page)
- Cell truncation with expand-on-click for long values
- Sticky header
- Keyboard navigation (arrow keys, page up/down)
- Export current page as CSV

**Backend pagination:**
Add `?page=1&page_size=50` query params to:
- `GET /api/v1/catalogue/entities/{id}/preview` — currently returns fixed limit; add `offset`/`limit` params and return `{"rows": [...], "total": N}`
- `GET /api/v1/audit/logs`
- `GET /api/v1/audit/jobs`

**Apply DataPager to:**
- `CataloguePage` entity data tab (replace current fixed preview)
- `AuditPage` all three tabs

---

## 6. Silver Transform Flow (Safe Upsert)

### 6a. Guided transform creation

Extend Jonas's system prompt with silver-layer guidance:

```
## Silver transform rules
- Silver tables clean, type-cast, and deduplicate bronze data.
- Always use INSERT OR REPLACE (upsert) — never DROP or TRUNCATE silver tables.
- Every silver table must have a primary key column for upsert deduplication.
- Transforms must reference only physically existing bronze columns (check the catalogue context above).
- Before drafting, call list_transforms to check if one exists — update it instead.
```

**Agent conversation pattern:**
1. User: "Clean up the orders table"
2. Jonas: calls `describe_entity` for `bronze.orders`, checks physical columns
3. Jonas: proposes silver schema (casts, renames, PK selection) — shows as `jonas-form` card or bullet summary
4. User confirms
5. Jonas: calls `draft_transform` with `INSERT OR REPLACE INTO silver.orders SELECT ...`

### 6b. Enforce SELECT + UPSERT only

In `transforms/service.py` `execute_transform`:

```python
_ALLOWED_STATEMENTS = re.compile(
    r"^\s*(SELECT|INSERT\s+OR\s+REPLACE|INSERT\s+OR\s+IGNORE|CREATE\s+TABLE\s+.*\s+AS\s+SELECT)",
    re.IGNORECASE | re.DOTALL
)

def _validate_transform_sql(sql: str):
    if not _ALLOWED_STATEMENTS.match(sql.strip()):
        raise ValueError(
            "Transform SQL must be SELECT, INSERT OR REPLACE, or CREATE TABLE AS SELECT. "
            "DROP, DELETE, UPDATE, and TRUNCATE are not permitted."
        )
```

Call `_validate_transform_sql` in both `create_transform` and `execute_transform`.

Similarly validate in `run_sql` tool — only SELECT is permitted there (already enforced).

### 6c. Upsert pattern for silver tables

Standard pattern Jonas should emit for silver transforms:

```sql
-- Ensure target table exists
CREATE TABLE IF NOT EXISTS silver.orders (
    order_id VARCHAR PRIMARY KEY,
    customer_id VARCHAR,
    amount DOUBLE,
    status VARCHAR,
    ordered_at TIMESTAMP,
    _ingested_at TIMESTAMP DEFAULT now()
);

-- Upsert from bronze
INSERT OR REPLACE INTO silver.orders
SELECT
    json_extract(payload, '$.order_id')   AS order_id,
    json_extract(payload, '$.customer')   AS customer_id,
    CAST(json_extract(payload, '$.total') AS DOUBLE) AS amount,
    json_extract(payload, '$.status')     AS status,
    CAST(json_extract(payload, '$.ts')    AS TIMESTAMP) AS ordered_at,
    now() AS _ingested_at
FROM bronze.orders
WHERE json_extract(payload, '$.order_id') IS NOT NULL;
```

---

## Implementation Sequence

| Step | Work | Files |
|------|------|-------|
| 1 | Rename integrations → connectors | DB migration, service, router, models, tools, frontend |
| 2 | `discover_api` tool + SSRF guard | `agent/tools.py`, `agent/service.py`, `pyproject.toml` (`httpx`) |
| 3 | `jonas-form` chat card protocol | `ChatPage.tsx`, new `ConnectorFormCard.tsx` |
| 4 | Cron schedule column + APScheduler | DB migration, `scheduler/scheduler.py`, `main.py`, `pyproject.toml` |
| 5 | Cron UI in ConnectorsPage | `ConnectorsPage.tsx`, `cronstrue` npm dep |
| 6 | Chat session persistence | DB migration, `agent/router.py`, `audit/router.py` |
| 7 | `AuditPage.tsx` | New page, sidebar entry in `App.tsx` |
| 8 | `DataPager.tsx` + backend pagination | New component, preview endpoint, audit endpoints |
| 9 | Silver transform SQL validation | `transforms/service.py` |
| 10 | Silver guidance in agent prompt | `agent/service.py` `_BASE_SYSTEM_PROMPT` |

---

## Open Questions

- **Secrets management**: API keys in connector `config` are stored in DuckDB plaintext. Consider env-var references (`{{MY_SECRET}}`) resolved at pull time from a secrets store or `.env`.
- **Pagination strategy**: DuckDB doesn't have native `COUNT(*)` with pagination efficiently for large tables — may need approximate counts or skip total for very large datasets.
- **Scheduler persistence**: APScheduler in-memory jobs are lost on restart. Use `SQLAlchemyJobStore` or simply reload from DB on startup (simpler, already planned).
- **`jonas-form` fallback**: If user is on a client that doesn't render form cards, Jonas should fall back to conversational field collection automatically.
