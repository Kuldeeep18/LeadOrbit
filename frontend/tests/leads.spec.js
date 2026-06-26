// @ts-check
const { test, expect, seedAuthTokens } = require('./fixtures');

const MOCK_LEADS = [
  {
    id: 'lead-001',
    first_name: 'Alice',
    last_name: 'Smith',
    email: 'alice@acme.test',
    phone: '555-0001',
    company: 'Acme Corp',
    score: 85,
    global_unsubscribe: false,
    tags: [],
  },
  {
    id: 'lead-002',
    first_name: 'Bob',
    last_name: 'Jones',
    email: 'bob@acme.test',
    phone: '555-0002',
    company: 'Beta Inc',
    score: 60,
    global_unsubscribe: true,
    tags: [],
  },
];

const MOCK_IMPORT_JOBS = [];

test.describe('Leads page', () => {
  test.beforeEach(async ({ page }) => {
    await seedAuthTokens(page);
  });

  test('leads table renders with correct data', async ({ page, mockApi }) => {
    await mockApi('**/api/v1/leads/**', MOCK_LEADS);
    await mockApi('**/api/v1/lead-import-jobs/**', MOCK_IMPORT_JOBS);
    await mockApi('**/api/v1/tags/**', []);

    await page.goto('/leads.html');

    await expect(page.locator('#leads-table-body')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('#leads-table-body')).toContainText('Alice');
    await expect(page.locator('#leads-table-body')).toContainText('bob@acme.test');
  });

  test('KPI counts are correct', async ({ page, mockApi }) => {
    await mockApi('**/api/v1/leads/**', MOCK_LEADS);
    await mockApi('**/api/v1/lead-import-jobs/**', MOCK_IMPORT_JOBS);
    await mockApi('**/api/v1/tags/**', []);

    await page.goto('/leads.html');

    await expect(page.locator('#leads-count')).toHaveText('2', { timeout: 10000 });
    await expect(page.locator('#active-leads-count')).toHaveText('1');
    await expect(page.locator('#unsubscribed-count')).toHaveText('1');
  });

  test('search filters leads by name or email', async ({ page, mockApi }) => {
    await mockApi('**/api/v1/leads/**', MOCK_LEADS);
    await mockApi('**/api/v1/lead-import-jobs/**', MOCK_IMPORT_JOBS);
    await mockApi('**/api/v1/tags/**', []);

    await page.goto('/leads.html');

    await expect(page.locator('#leads-table-body')).toContainText('Alice', { timeout: 10000 });

    await page.locator('#lead-search').fill('bob');

    await expect(page.locator('#leads-table-body')).toContainText('bob@acme.test');
    await expect(page.locator('#leads-table-body')).not.toContainText('Alice');
  });

  test('filter panel opens when Filters button is clicked', async ({ page, mockApi }) => {
    await mockApi('**/api/v1/leads/**', MOCK_LEADS);
    await mockApi('**/api/v1/lead-import-jobs/**', MOCK_IMPORT_JOBS);
    await mockApi('**/api/v1/tags/**', []);

    await page.goto('/leads.html');

    await expect(page.locator('#filter-panel')).toBeHidden();
    await page.locator('#filter-toggle-btn').click();
    await expect(page.locator('#filter-panel')).toBeVisible();
  });

  test('CSV import modal opens when Import CSV is clicked', async ({ page, mockApi }) => {
    await mockApi('**/api/v1/leads/**', MOCK_LEADS);
    await mockApi('**/api/v1/lead-import-jobs/**', MOCK_IMPORT_JOBS);
    await mockApi('**/api/v1/tags/**', []);

    await page.goto('/leads.html');

    await page.getByRole('button', { name: /import csv/i }).click();
    await expect(page.locator('#uploadModal')).toBeVisible({ timeout: 5000 });
  });
});
