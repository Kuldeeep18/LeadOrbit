// @ts-check
const { test, expect, seedAuthTokens } = require('./fixtures');

const MOCK_CAMPAIGNS = [
  {
    id: 'camp-001',
    name: 'Q1 Outreach',
    status: 'ACTIVE',
    enrolled_leads: [],
    steps: [{ id: 's1' }, { id: 's2' }],
    connected_account: null,
  },
  {
    id: 'camp-002',
    name: 'Cold Email Blast',
    status: 'DRAFT',
    enrolled_leads: [],
    steps: [{ id: 's3' }],
    connected_account: null,
  },
  {
    id: 'camp-003',
    name: 'Follow Up Sequence',
    status: 'PAUSED',
    enrolled_leads: [],
    steps: [],
    connected_account: null,
  },
];

test.describe('Campaigns list', () => {
  test.beforeEach(async ({ page }) => {
    await seedAuthTokens(page);
  });

  test('campaigns render in the grid', async ({ page, mockApi }) => {
    await mockApi('**/api/v1/campaigns/**', MOCK_CAMPAIGNS);

    await page.goto('/campaigns.html');

    await expect(page.locator('#campaigns-grid')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('#campaigns-grid')).toContainText('Q1 Outreach');
    await expect(page.locator('#campaigns-grid')).toContainText('Cold Email Blast');
    await expect(page.locator('#campaigns-grid')).toContainText('Follow Up Sequence');
  });

  test('search filters campaigns by name', async ({ page, mockApi }) => {
    await mockApi('**/api/v1/campaigns/**', MOCK_CAMPAIGNS);

    await page.goto('/campaigns.html');

    await expect(page.locator('#campaigns-grid')).toContainText('Q1 Outreach', { timeout: 10000 });

    await page.locator('#campaign-search').fill('Cold');

    await expect(page.locator('#campaigns-grid')).toContainText('Cold Email Blast');
    await expect(page.locator('#campaigns-grid')).not.toContainText('Q1 Outreach');
  });

  test('stats show correct total count', async ({ page, mockApi }) => {
    await mockApi('**/api/v1/campaigns/**', MOCK_CAMPAIGNS);

    await page.goto('/campaigns.html');

    await expect(page.locator('#stat-total')).toHaveText('3', { timeout: 10000 });
    await expect(page.locator('#stat-active')).toHaveText('1');
  });

  test('empty state shows when no campaigns exist', async ({ page, mockApi }) => {
    await mockApi('**/api/v1/campaigns/**', []);

    await page.goto('/campaigns.html');

    await expect(page.locator('#campaigns-grid')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('#stat-total')).toHaveText('0');
  });
});
