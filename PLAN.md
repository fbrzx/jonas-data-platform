# PLAN.md — Manual Editing of Items via Dashboard Forms with RBAC

## 1. Current State Assessment

### What exists today

**Backend:**
- `catalogue/router.py` already has `PATCH /entities/{id}` and `EntityUpdate` model — but not wired to the frontend
- `catalogue/router.py` has `POST /entities/{id}/fields` (bulk create) but no field-level update or delete
- `transforms/router.py` has no PATCH endpoint; edits are not possible via the API at all
- `integrations/router.py` has no PATCH endpoint; only create and delete exist
- Permission checks use `require_permission(user, Resource.X, Action.WRITE)` — `WRITE` is already granted to `admin` and `analyst` for all three resources

**Frontend:**
- `IntegrationsPage.tsx` has a `CreateModal` — the **only edit form** in the system and the pattern to follow
- `CataloguePage.tsx` — read-only; no edit affordances
- `TransformsPage.tsx` — approve/reject/execute only; no edit form
- `apps/dashboard/src/lib/api.ts` — no `update` method on any namespace; all need to be added
- `main.py` CORS allows `PATCH` but not `PUT` — use `PATCH` throughout

### Gap Summary

| Feature | Backend API | Frontend form | Permission check |
|---|---|---|---|
| Edit entity (name, description, tags) | EXISTS (PATCH /catalogue/entities/{id}) | MISSING | EXISTS |
| Edit entity fields (is_pii, data_type, description) | MISSING | MISSING | EXISTS |
| Edit transform (name, description, SQL — draft only) | MISSING | MISSING | EXISTS |
| Edit integration (name, description, status) | MISSING | MISSING | EXISTS |
| Frontend permission guard hook | — | MISSING | N/A |

---

## 2. RBAC Matrix

| Role | Catalogue edit | Transform edit | Integration edit | Approve transforms |
|---|---|---|---|---|
| admin | YES | YES (any status) | YES | YES |
| analyst | YES | YES (draft only) | YES | NO |
| viewer | NO | NO | NO | NO |

**Key rules to enforce in UI:**
1. Viewers see no edit buttons
2. Analysts can edit transforms only when `status === 'draft'`; locked after submission
3. Admins can edit anything regardless of status
4. `connector_type` on integrations is immutable after creation
5. Entity `layer` is immutable after creation
6. Entity/integration `name` edits are admin-only with a prominent warning (maps to DuckDB table names)
7. Transform `sql` is editable only while `status === 'draft'`; service strips it otherwise

**Frontend permission helper** (new `usePermissions` hook):
```typescript
canWrite  = role === 'admin' || role === 'analyst'
canAdmin  = role === 'admin'
canApprove = role === 'admin'
```

---

## 3. Backend Changes

### 3.1 Transforms — add `TransformUpdate` model + PATCH endpoint

**`transforms/models.py`** — add:
```python
class TransformUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    sql: str | None = None           # only respected when status=draft
    source_layer: str | None = None  # only respected when status=draft
    target_layer: str | None = None  # only respected when status=draft
    tags: list[str] | None = None
```

**`transforms/service.py`** — add `update_transform()`:
- Follow set-clause pattern from `catalogue/service.py:update_entity`
- Strip `sql`, `source_layer`, `target_layer` when `existing['status'] != 'draft'`
- Update `updated_at = current_timestamp`
- Catch uniqueness constraint violations → surface as 409

**`transforms/router.py`** — add:
```python
@router.patch("/{transform_id}")
async def update_transform(transform_id: UUID, body: TransformUpdate, request: Request):
    require_permission(_user(request), Resource.TRANSFORM, Action.WRITE)
    ...
```
Also expose the existing `create_transform` service function (currently unrouted) as `POST /`.

### 3.2 Integrations — add `IntegrationUpdate` model + PATCH endpoint

**`integrations/models.py`** — add:
```python
class IntegrationUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None   # active | paused
    config: dict[str, Any] | None = None
    tags: list[str] | None = None
    # connector_type deliberately excluded — immutable
```

**`integrations/service.py`** — add `update_integration()`:
- Always strip `connector_type` from payload (immutable)
- Update `updated_at`

**`integrations/router.py`** — add `PATCH /{integration_id}` with `require_permission(WRITE)`.

### 3.3 Entity fields — add PATCH + DELETE per-field endpoints

**`catalogue/service.py`** — add:
- `update_field(field_id, data)` — updatable fields: `data_type`, `nullable`, `is_pii`, `description`
- `delete_field(field_id, entity_id)` — hard delete

**`catalogue/router.py`** — add:
- `PATCH /entities/{entity_id}/fields/{field_id}` — `require_permission(WRITE)`
- `DELETE /entities/{entity_id}/fields/{field_id}` — `require_permission(WRITE)` (admin-only in UI)

### 3.4 No changes to `main.py`

`PATCH` is already in CORS `allow_methods`. No new routers to mount.

---

## 4. Frontend Changes

### 4.1 API client (`apps/dashboard/src/lib/api.ts`)

Add interfaces:
```typescript
export interface IntegrationUpdate { name?: string; description?: string; status?: 'active' | 'paused'; config?: Record<string, unknown>; tags?: string[] }
export interface TransformCreate { name: string; description?: string; source_layer: string; target_layer: string; sql: string; tags?: string[] }
export interface TransformUpdate { name?: string; description?: string; sql?: string; source_layer?: string; target_layer?: string; tags?: string[] }
```

Add methods:
```typescript
api.catalogue.update(id, body)          // PATCH /catalogue/entities/{id}
api.catalogue.updateField(eid, fid, b)  // PATCH /catalogue/entities/{eid}/fields/{fid}
api.integrations.update(id, body)       // PATCH /integrations/{id}
api.transforms.update(id, body)         // PATCH /transforms/{id}
api.transforms.create(body)             // POST  /transforms
```

### 4.2 Permission hook (`apps/dashboard/src/lib/permissions.ts` — new file)

```typescript
export function usePermissions() {
  const role = getRoleFromToken(getToken())
  return { role, canWrite: role === 'admin' || role === 'analyst', canAdmin: role === 'admin', canApprove: role === 'admin' }
}
```

### 4.3 CataloguePage

- Add "Edit" button to `EntityRow` header (visible when `canWrite`)
- Opens `EditEntityModal`: `name` (admin-only with rename warning), `description`, `tags`
- Per-field pencil icon in field table (visible when `canWrite`) → `EditFieldModal`
- `EditFieldModal`: `data_type` (select), `nullable` (checkbox), `is_pii` (checkbox with red warning), `description`; `name` is read-only
- Admin-only trash icon per field row → `delete_field`

### 4.4 TransformsPage

- "New Transform" button in page header (visible when `canWrite`) → `CreateTransformModal`
- "Edit" button on `TransformCard` (visible when `canWrite && status === 'draft'` for analysts; any status for admins)
- `EditTransformModal` / `CreateTransformModal`: `name`, `description`, `source_layer`, `target_layer`, `sql` (textarea, monospace, min-height 200px), `tags`
- When `status !== 'draft'`, show warning banner and disable `sql`/layer fields

### 4.5 IntegrationsPage

- "Edit" (pencil) button on `IntegrationCard` (visible when `canWrite`)
- `EditIntegrationModal`: `connector_type` (read-only display), `name` (admin-only with warning), `description`, `status` (select: active/paused)

---

## 5. Implementation Order

| Step | What | Files |
|---|---|---|
| 1 | Backend: Transforms PATCH + POST create | `transforms/models.py`, `transforms/service.py`, `transforms/router.py` |
| 2 | Backend: Integrations PATCH | `integrations/models.py`, `integrations/service.py`, `integrations/router.py` |
| 3 | Backend: Entity field PATCH + DELETE | `catalogue/service.py`, `catalogue/router.py` |
| 4 | Frontend: API client additions + new interfaces | `apps/dashboard/src/lib/api.ts` |
| 5 | Frontend: `usePermissions` hook | `apps/dashboard/src/lib/permissions.ts` (new) |
| 6 | Frontend: CataloguePage entity edit form | `CataloguePage.tsx` |
| 7 | Frontend: CataloguePage field edit form | `CataloguePage.tsx` |
| 8 | Frontend: TransformsPage edit + create forms | `TransformsPage.tsx` |
| 9 | Frontend: IntegrationsPage edit form | `IntegrationsPage.tsx` |
| 10 | End-to-end verification (see test matrix below) | — |

### Test Matrix

| Token | Action | Expected |
|---|---|---|
| admin-token | Edit entity name | 200 OK, name updates |
| admin-token | Toggle field is_pii | 200 OK, preview masks/unmasks |
| admin-token | Edit transform SQL (any status) | 200 OK |
| admin-token | Edit integration status → paused | 200 OK |
| analyst-token | Edit entity description | 200 OK |
| analyst-token | Edit transform SQL when draft | 200 OK |
| analyst-token | Edit transform SQL when approved | 200 OK (service strips sql field) |
| analyst-token | Approve transform | 403 Forbidden |
| viewer-token | Any edit action | Edit buttons not visible; 403 if API hit directly |

---

## 6. Key Implementation Notes

- **Service is the authority**: SQL-field immutability for non-draft transforms is enforced in the service layer, not just the UI
- **`updated_at`**: Every update function must set `updated_at = current_timestamp` — follow `update_entity` pattern
- **Name uniqueness**: Catch DuckDB uniqueness violations in service and surface as 409
- **Field name immutability**: `entity_field.name` must never be editable — display as read-only label
- **PATCH not PUT**: CORS only allows PATCH; use consistently throughout

### Critical Reference Files
- `services/api/src/catalogue/service.py` — `update_entity` is the pattern to replicate for all update service functions
- `apps/dashboard/src/pages/IntegrationsPage.tsx` — `CreateModal` is the component pattern to replicate for all edit modals
- `services/api/src/auth/permissions.py` — `ROLE_DEFAULTS`; do not modify, use existing `Action.WRITE` pattern
