# Quick Refactor: Unit Tests for the UI

> Scope: medium — set up testing infrastructure, write foundational tests

## Current State

- Zero test files, no test runner configured
- No testing dependencies in `apps/dashboard/package.json`
- Stack: Vite + React 19 + TypeScript + TanStack Query + React Router

## Plan

### 1. Set up Vitest + Testing Library

**File:** `apps/dashboard/package.json` — add devDependencies:
```json
{
  "vitest": "^3.0.0",
  "@testing-library/react": "^16.0.0",
  "@testing-library/jest-dom": "^6.0.0",
  "@testing-library/user-event": "^14.0.0",
  "jsdom": "^25.0.0",
  "@vitejs/plugin-react": "already present"
}
```

Add script:
```json
"test": "vitest",
"test:ci": "vitest run --coverage"
```

**File:** `apps/dashboard/vitest.config.ts`
```typescript
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
```

**File:** `apps/dashboard/src/test/setup.ts`
```typescript
import '@testing-library/jest-dom'
```

### 2. Test utilities

**File:** `apps/dashboard/src/test/helpers.tsx`

```typescript
// Render wrapper with providers (QueryClient, Router, etc.)
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

export function renderWithProviders(ui: React.ReactElement, options?: {
  route?: string
  queryClient?: QueryClient
}) {
  const queryClient = options?.queryClient ?? new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[options?.route ?? '/']}>
        {ui}
      </MemoryRouter>
    </QueryClientProvider>
  )
}

// Mock API responses
export function mockFetch(responses: Record<string, unknown>) {
  // Override global fetch with pattern-matched responses
}
```

### 3. Test plan by priority

#### Tier 1: Utility / logic tests (no DOM, fast)

| File | Tests | What |
|------|-------|------|
| `lib/permissions.test.ts` | 5-8 | `usePermissions` returns correct booleans per role (admin/analyst/viewer) |
| `lib/api.test.ts` | 5-6 | API client builds correct URLs, handles errors, token management |

#### Tier 2: Component tests (shared components — after Dialog refactor)

| File | Tests | What |
|------|-------|------|
| `components/Dialog.test.tsx` | 4-5 | Renders when open, closes on escape, closes on backdrop, focus trap |
| `components/ConfirmDialog.test.tsx` | 3-4 | Shows message, calls onConfirm, calls onClose, disabled when loading |
| `components/Badge.test.tsx` | 3 | Renders label, applies variant classes |
| `components/Toast.test.tsx` | 3-4 | Shows toast, auto-dismisses, supports variants |

#### Tier 3: Page smoke tests (renders without crash, key elements present)

| File | Tests | What |
|------|-------|------|
| `pages/DashboardPage.test.tsx` | 2-3 | Renders stats skeleton, shows data after load |
| `pages/CataloguePage.test.tsx` | 4-5 | Renders entity list, expands fields, opens edit modal, data preview tab |
| `pages/TransformsPage.test.tsx` | 3-4 | Renders transform cards, status filter, create modal opens |
| `pages/IntegrationsPage.test.tsx` | 3-4 | Renders integration cards, upload modal, create modal |
| `pages/ChatPage.test.tsx` | 3-4 | Renders input, sends message, displays response stream |
| `pages/LineagePage.test.tsx` | 2 | Renders 3 columns, shows entities in correct layers |

#### Tier 4: Integration-style tests (user flows)

| File | Tests | What |
|------|-------|------|
| `flows/entity-crud.test.tsx` | 3 | Create entity via modal, edit name, delete with confirmation |
| `flows/transform-lifecycle.test.tsx` | 3 | Draft transform, approve (admin), execute |
| `flows/role-switching.test.tsx` | 3 | Switch token, verify UI updates (buttons hidden/shown per role) |

### 4. Mocking strategy

- **API calls:** Mock `fetch` globally in setup, provide per-test response overrides
- **TanStack Query:** Use real QueryClient with `retry: false` — tests hit mocked fetch
- **Router:** Use `MemoryRouter` with controlled initial route
- **No MSW initially** — plain fetch mocks are sufficient for this scale; add MSW if mocking gets complex

### 5. CI integration

Add to `Makefile`:
```makefile
test-ui:
	cd apps/dashboard && pnpm test:ci
```

Add to root `package.json` scripts:
```json
"test:dashboard": "pnpm --filter dashboard test:ci"
```

## Implementation Order

1. Install deps + vitest config + setup file
2. `lib/permissions.test.ts` + `lib/api.test.ts` (fast wins, no DOM)
3. Shared component tests (after Dialog refactor)
4. Page smoke tests (one per page)
5. Integration flow tests (last, most complex)

## Target Coverage

- Tier 1 + 2: ~80% of shared logic and components
- Tier 3: every page renders without errors
- Tier 4: critical user flows don't regress
- Goal: ~50-60% line coverage as a foundation, not 100%
