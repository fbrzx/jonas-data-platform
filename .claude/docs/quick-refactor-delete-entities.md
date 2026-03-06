# Quick Refactor: Delete Entities (Admin Only)

> Scope: small — backend exists, frontend needs button + confirmation

## Current State

- **Backend:** `DELETE /api/v1/catalogue/entities/{entity_id}` exists in `catalogue/router.py:122-127`
- **Service:** `delete_entity()` in `catalogue/service.py:106-114` — simple DELETE with tenant isolation
- **Permission:** Already gated on `WRITE` permission for `CATALOGUE` resource
- **Frontend:** No delete button or confirmation dialog in `CataloguePage.tsx`

## Plan

### 1. Tighten backend to admin-only

Currently uses `WRITE` on `CATALOGUE` — engineers also have write access. Change to explicit admin check.

**File:** `services/api/src/catalogue/router.py`
```python
# In delete_entity endpoint — add admin role check
if user.role != "admin":
    raise HTTPException(403, "Only admins can delete entities")
```

Also add cascade behavior — when deleting an entity:
- Delete all `entity_field` rows for that entity
- Delete any `entity_lineage` rows referencing it (source or target)
- Delete the physical bronze/silver/gold table if it exists (optional, flag-controlled)
- Log to `audit.audit_log`

**File:** `services/api/src/catalogue/service.py`
```python
def delete_entity(conn, tenant_id: str, entity_id: str, drop_table: bool = False):
    # 1. Delete fields
    # 2. Delete lineage references
    # 3. Optionally DROP the physical table
    # 4. Delete entity row
    # 5. Audit log entry
```

### 2. Add delete button + confirmation in CataloguePage

**File:** `apps/dashboard/src/pages/CataloguePage.tsx`

- Add a red trash icon button next to the edit button on each entity row (admin only)
- On click, show a confirmation dialog: "Delete entity {name}? This will remove all fields and lineage. This cannot be undone."
- Checkbox option: "Also drop the physical data table" (default unchecked)
- On confirm, call `DELETE /api/v1/catalogue/entities/{id}?drop_table=true|false`
- Invalidate `entities` query on success
- Use the existing inline modal pattern from `EditEntityModal`

### 3. Agent tool awareness

Add entity deletion as a tool the agent can invoke (admin sessions only):

**File:** `services/api/src/agent/tools.py`
- New tool: `delete_entity` — requires entity_id, confirms with user before executing
- Agent system prompt addition: "You can delete entities for admin users. Always confirm before deleting."

## Estimate

- Backend hardening: ~30 lines changed across 2 files
- Frontend dialog: ~60 lines (follows existing modal pattern)
- Agent tool: ~20 lines
- Total: ~110 lines, no new dependencies
