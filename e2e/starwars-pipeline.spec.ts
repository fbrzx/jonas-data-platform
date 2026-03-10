/**
 * Star Wars Pipeline — End-to-End Test
 *
 * Covers:
 *  1.  Create "Test" tenant via SuperUser page
 *  2.  Enter the tenant
 *  3.  Import the Star Wars collection JSON
 *  4.  Pull data from all api_pull connectors
 *  5.  Approve all draft transforms
 *  6.  Execute all approved transforms
 *  7.  Create a dashboard (via API)
 *  8.  Delete the dashboard via the Dashboards page
 *  9.  Delete all transforms
 *  10. Delete all connectors
 *  11. Delete all entities (via API for reliability)
 *  12. Deactivate the tenant via SuperUser page
 *
 * All confirm dialogs are custom React modals (ToastProvider) — no native window.confirm.
 *
 * Prerequisites:
 *  - `make up`   — API running on :8000
 *  - `pnpm dev`  — Dashboard running on :5173
 *  - ~/Downloads/collection-Star Wars.json exists
 */

import { test, expect, type Page } from '@playwright/test'

const SUPERUSER_TOKEN = 'superuser-token'
const TENANT_SLUG     = 'test'
const TENANT_NAME     = 'Test'
// Relative to the project root (where `playwright test` runs)
const STAR_WARS_FILE  = 'e2e/fixtures/collection-star-wars.json'
const API_BASE        = 'http://localhost:8000/api/v1'
const DASHBOARD_SLUG  = 'star-wars-overview'

// ── Helpers ────────────────────────────────────────────────────────────────────

function getAuthHeaders(page: Page): Promise<Record<string, string>> {
  return page.evaluate(() => {
    const token    = localStorage.getItem('jonas_token') ?? ''
    const tenantId = localStorage.getItem('jonas_active_tenant')
    return {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      ...(tenantId ? { 'X-Tenant-ID': tenantId } : {}),
    }
  })
}

/**
 * Client-side React Router navigation via sidebar link.
 * Waits for the link to be visible first (the SU sidebar only shows tenant
 * nav items after the Layout receives the jonas_tenant_changed event).
 */
async function navTo(page: Page, href: string) {
  const link = page.locator(`a[href="${href}"]`)
  await expect(link).toBeVisible({ timeout: 10_000 })
  await link.click()
  await page.waitForURL(`**${href}`)
}

/** Click the custom modal "Confirm" button rendered by ToastProvider. */
async function clickModalConfirm(page: Page) {
  await page.getByRole('button', { name: 'Confirm' }).click()
}

// ── Test ───────────────────────────────────────────────────────────────────────

test('Star Wars pipeline — create → import → pull → approve → execute → dashboard → cleanup', async ({ page }) => {

  // ── 1. Authenticate as superuser ──────────────────────────────────────────
  //
  // addInitScript runs before any page script, so localStorage is populated
  // before React initializes — RequireAuth never redirects to /login.

  await page.addInitScript((token) => {
    localStorage.setItem('jonas_token', token)
  }, SUPERUSER_TOKEN)

  // historyApiFallback (vite.config.ts) serves index.html for /superuser
  await page.goto('http://localhost:5173/superuser')
  await expect(page.getByText('Platform Administration')).toBeVisible()

  // ── 2. Create "Test" tenant ───────────────────────────────────────────────

  await page.getByRole('button', { name: '+ New Tenant' }).click()
  await page.getByPlaceholder('my-tenant').fill(TENANT_SLUG)
  await page.getByPlaceholder('My Tenant').fill(TENANT_NAME)
  await page.getByRole('button', { name: 'Create' }).click()

  const tenantRow = page.locator('tr').filter({ hasText: TENANT_NAME })
  await expect(tenantRow).toBeVisible({ timeout: 10_000 })

  // ── 3. Enter "Test" tenant ────────────────────────────────────────────────
  //
  // Clicking "Enter →" calls setActiveTenantId (localStorage) + navigate('/').
  // We then wait for the Collections nav link to be visible — that confirms
  // the Layout's jonas_tenant_changed handler has run and the sidebar items
  // for a SU-in-tenant are rendered.

  await tenantRow.getByRole('button', { name: /Enter/ }).click()
  await page.waitForURL('http://localhost:5173/')

  // Wait for a tenant-only nav link to confirm the sidebar has updated
  await expect(page.locator('a[href="/collections"]')).toBeVisible({ timeout: 10_000 })

  // ── 4. Import Star Wars collection ────────────────────────────────────────

  await navTo(page, '/collections')
  await expect(page.locator('h2', { hasText: 'Collections' })).toBeVisible()

  // Hidden file input — Playwright can set files without clicking the label
  await page.locator('input[type="file"]').setInputFiles(STAR_WARS_FILE)

  // ImportSummary shows after a successful import
  await expect(page.getByText('Import complete — Star Wars')).toBeVisible({ timeout: 30_000 })

  // ── 5. Pull data from all api_pull connectors ─────────────────────────────
  //
  // page.waitForResponse does not intercept requests routed through Vite's
  // dev-server proxy (the CDP sees only the browser→:5173 hop, not the
  // :5173→:8000 leg). Toast-based waits are also fragile because the toast
  // auto-dismisses in 4.5 s and SWAPI can be slow. Use page.request instead:
  // it calls the API directly and returns only when the response is received.

  await navTo(page, '/connectors')
  await page.waitForLoadState('networkidle')

  // Verify pull buttons are present (confirms connectors were imported)
  const pullCount = await page.getByRole('button', { name: 'pull' }).count()
  expect(pullCount).toBeGreaterThan(0)

  // Fetch the connector list from the API and trigger each one directly
  const pullHeaders = await getAuthHeaders(page)
  const connectorsListResp = await page.request.get(`${API_BASE}/connectors`, {
    headers: pullHeaders,
  })
  expect(connectorsListResp.ok()).toBeTruthy()
  const allConnectors: Array<{ id: string; connector_type: string }> =
    await connectorsListResp.json()

  for (const connector of allConnectors.filter(c => c.connector_type === 'api_pull')) {
    const triggerResp = await page.request.post(
      `${API_BASE}/connectors/${connector.id}/trigger`,
      { headers: pullHeaders, timeout: 60_000 },
    )
    expect(triggerResp.ok()).toBeTruthy()
  }

  // ── 6. Approve all draft transforms ──────────────────────────────────────
  //
  // Do NOT reload inside the loop — page.reload() kills the in-flight POST
  // before the backend finishes, leaving the transform in "draft" forever.
  // Instead: fetch the transform list via API, approve each one directly,
  // then navigate to /transforms only to verify the UI reflects the changes.

  const approveHeaders = await getAuthHeaders(page)
  const transformsListResp = await page.request.get(`${API_BASE}/transforms`, {
    headers: approveHeaders,
  })
  expect(transformsListResp.ok()).toBeTruthy()
  const allTransforms: Array<{ id: string; status: string }> =
    await transformsListResp.json()

  for (const transform of allTransforms.filter(t => t.status === 'draft')) {
    const approveResp = await page.request.post(
      `${API_BASE}/transforms/${transform.id}/approval`,
      { headers: approveHeaders, data: { action: 'approve' } },
    )
    expect(approveResp.ok()).toBeTruthy()
  }

  // ── 7. Execute all approved transforms ───────────────────────────────────
  //
  // Same pattern: fetch via API, execute each one directly.
  // Transforms may take a few seconds each; use a generous timeout.

  const execHeaders = await getAuthHeaders(page)
  const approvedListResp = await page.request.get(`${API_BASE}/transforms`, {
    headers: execHeaders,
  })
  expect(approvedListResp.ok()).toBeTruthy()
  const approvedTransforms: Array<{ id: string; status: string }> =
    await approvedListResp.json()

  for (const transform of approvedTransforms.filter(t => t.status === 'approved')) {
    const execResp = await page.request.post(
      `${API_BASE}/transforms/${transform.id}/execute`,
      { headers: execHeaders, timeout: 60_000 },
    )
    expect(execResp.ok()).toBeTruthy()
  }

  // ── 8. Create dashboard (via API) ─────────────────────────────────────────

  const headers = await getAuthHeaders(page)

  const createResp = await page.request.put(`${API_BASE}/dashboards/${DASHBOARD_SLUG}`, {
    headers,
    data: {
      content: `---\ntitle: Star Wars Overview\n---\n\n# Star Wars Overview\n\nSWAPI pipeline summary.\n`,
    },
  })
  expect(createResp.ok()).toBeTruthy()

  // ── 9. Delete the dashboard via Dashboards UI ─────────────────────────────

  await navTo(page, '/dashboards')

  // Wait for the EditorPanel to fully render (title appears in the toolbar
  // AND in the MarkdownPreview — either confirms the panel is ready)
  await expect(page.getByRole('heading', { name: 'Star Wars Overview' })).toBeVisible({ timeout: 10_000 })

  await page.getByRole('button', { name: 'delete' }).click()
  await clickModalConfirm(page)

  // After delete onSuccess: setSelection(null) unmounts EditorPanel,
  // invalidateQueries refetches the list (returns []), EmptyState renders.
  // "No dashboards yet" appearing confirms both the delete AND the refetch completed.
  await expect(page.getByText('No dashboards yet')).toBeVisible({ timeout: 15_000 })

  // ── 10. Delete all transforms ─────────────────────────────────────────────
  //
  // Use API directly — avoids reload-kills-mutation race.

  const deleteTransformHeaders = await getAuthHeaders(page)
  const transformsForDelete: Array<{ id: string }> =
    await (await page.request.get(`${API_BASE}/transforms`, { headers: deleteTransformHeaders })).json()

  for (const t of transformsForDelete) {
    const delResp = await page.request.delete(`${API_BASE}/transforms/${t.id}`, {
      headers: deleteTransformHeaders,
    })
    expect(delResp.status()).toBeLessThan(300)
  }

  // ── 11. Delete all connectors ─────────────────────────────────────────────
  //
  // Use API directly for the same reason.

  const deleteConnectorHeaders = await getAuthHeaders(page)
  const connectorsForDelete: Array<{ id: string }> =
    await (await page.request.get(`${API_BASE}/connectors`, { headers: deleteConnectorHeaders })).json()

  for (const c of connectorsForDelete) {
    const delResp = await page.request.delete(`${API_BASE}/connectors/${c.id}`, {
      headers: deleteConnectorHeaders,
    })
    expect(delResp.status()).toBeLessThan(300)
  }

  // ── 12. Delete all entities (via API) ────────────────────────────────────

  const freshHeaders = await getAuthHeaders(page)

  const entitiesResp = await page.request.get(`${API_BASE}/catalogue/entities`, {
    headers: freshHeaders,
  })
  expect(entitiesResp.ok()).toBeTruthy()
  const entities: Array<{ id: string }> = await entitiesResp.json()

  for (const entity of entities) {
    const delResp = await page.request.delete(`${API_BASE}/catalogue/entities/${entity.id}`, {
      headers: freshHeaders,
    })
    expect(delResp.status()).toBeLessThan(300)
  }

  // ── 13. Deactivate the tenant ─────────────────────────────────────────────

  // The header shows an "Exit tenant scope" button for SU-in-tenant
  await page.locator('button[title="Exit tenant scope"]').click()
  await page.waitForURL('**/superuser')
  await expect(page.getByText('Platform Administration')).toBeVisible()
  // Let stale background refetches from tenant pages settle before clicking Deactivate.
  // Without this, a refetch firing without X-Tenant-ID returns 401, which (in older code)
  // would clear the access token and cause the Deactivate request to send empty auth → 403.
  await page.waitForLoadState('networkidle')

  const testRow = page.locator('tr').filter({ hasText: TENANT_NAME })
  await expect(testRow).toBeVisible()

  await testRow.getByRole('button', { name: 'Deactivate' }).click()
  await clickModalConfirm(page)

  await expect(page.locator('tr').filter({ hasText: TENANT_NAME })).not.toBeVisible({ timeout: 10_000 })
})
