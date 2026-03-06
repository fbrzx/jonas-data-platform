# Quick Refactor: Dialogs & General UI Improvements

> Scope: medium — extract shared dialog, standardise patterns, polish UX

## Current State

- 7 modal implementations across 3 pages, all using the same inline pattern
- No shared `Dialog` or `Modal` component
- No `components/` directory — everything lives in page files
- Pages are large monoliths (CataloguePage: 578 lines, IntegrationsPage: 731 lines)
- No UI library (shadcn/ui, Radix, Headless UI) — pure Tailwind
- Custom theme via CSS variables (`--j-bg`, `--j-surface`, `--j-accent`, etc.)

## Plan

### 1. Create shared Dialog component

**New file:** `apps/dashboard/src/components/Dialog.tsx`

```typescript
interface DialogProps {
  open: boolean
  onClose: () => void
  title: string
  maxWidth?: string        // default "max-w-lg"
  children: React.ReactNode
  footer?: React.ReactNode  // optional action buttons area
}
```

Features:
- Backdrop click to close
- Escape key to close
- Focus trap (basic: auto-focus first input)
- Portal rendering via `createPortal`
- Matches existing visual pattern: `bg-j-surface border-j-border rounded-lg`

### 2. Create ConfirmDialog variant

**New file:** `apps/dashboard/src/components/ConfirmDialog.tsx`

```typescript
interface ConfirmDialogProps {
  open: boolean
  onClose: () => void
  onConfirm: () => void
  title: string
  message: string
  confirmLabel?: string    // default "Confirm"
  confirmVariant?: "danger" | "primary"  // red vs accent
  loading?: boolean
}
```

Use for: entity deletion, transform rejection, integration deactivation.

### 3. Refactor existing modals to use Dialog

Migrate each existing modal to wrap `<Dialog>`:

| Page | Modal | Change |
|------|-------|--------|
| CataloguePage | EditEntityModal | Wrap with `<Dialog>`, extract to `components/EditEntityDialog.tsx` |
| CataloguePage | EditFieldModal | Wrap with `<Dialog>`, extract to `components/EditFieldDialog.tsx` |
| TransformsPage | TransformFormModal | Wrap with `<Dialog>`, keep inline (tightly coupled to page state) |
| IntegrationsPage | CreateModal | Wrap with `<Dialog>`, extract to `components/CreateIntegrationDialog.tsx` |
| IntegrationsPage | EditIntegrationModal | Wrap with `<Dialog>`, extract to `components/EditIntegrationDialog.tsx` |
| IntegrationsPage | UploadModal | Wrap with `<Dialog>`, keep inline (simple) |
| CataloguePage | Delete confirm (new) | Use `<ConfirmDialog>` |

### 4. General UI improvements

**a) Form inputs — shared styles**

**New file:** `apps/dashboard/src/components/FormField.tsx`
```typescript
// Label + input/select/textarea with consistent styling
interface FormFieldProps {
  label: string
  required?: boolean
  error?: string
  children: React.ReactNode  // the actual input element
}
```

**b) Badge component**

**New file:** `apps/dashboard/src/components/Badge.tsx`
```typescript
// Status badges used everywhere (transform status, layer, PII flag)
interface BadgeProps {
  label: string
  variant: "success" | "warning" | "danger" | "info" | "neutral"
}
```

**c) Empty states**

Add consistent empty state illustrations/messages when:
- No entities in a layer
- No transforms created
- No integrations configured
- No chat history

**d) Toast notifications**

**New file:** `apps/dashboard/src/components/Toast.tsx`
- Simple toast context + provider
- Replace `alert()` calls and silent failures with visible feedback
- Auto-dismiss after 3s, closeable
- Variants: success (green), error (red), info (accent)

**e) Loading skeletons**

Replace plain "Loading..." text with skeleton placeholders matching the layout of the content being loaded (table rows, cards, stats).

### 5. File organization after refactor

```
apps/dashboard/src/
  components/
    Dialog.tsx           ~50 lines
    ConfirmDialog.tsx    ~30 lines
    FormField.tsx        ~25 lines
    Badge.tsx            ~20 lines
    Toast.tsx            ~60 lines
    Skeleton.tsx         ~30 lines
    EditEntityDialog.tsx    (extracted from CataloguePage)
    EditFieldDialog.tsx     (extracted from CataloguePage)
    CreateIntegrationDialog.tsx  (extracted from IntegrationsPage)
    EditIntegrationDialog.tsx    (extracted from IntegrationsPage)
  lib/
    api.ts
    permissions.ts
  pages/
    (unchanged, but each ~100-150 lines shorter)
```

## Implementation Order

1. `Dialog.tsx` + `ConfirmDialog.tsx` (foundation)
2. `Badge.tsx` + `FormField.tsx` (small, immediate reuse)
3. Migrate existing modals one page at a time
4. `Toast.tsx` + wire up mutations
5. Loading skeletons + empty states (polish pass)
