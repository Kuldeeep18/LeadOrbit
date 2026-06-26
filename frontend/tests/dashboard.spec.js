// @ts-check
const { test, expect, seedAuthTokens } = require('./fixtures');

const MOCK_DASHBOARD = {
  total_leads: 42,
  active_campaigns: 3,
  emails_sent: 150,
  opened: 80,
  replied: 20,
  clicked: 10,
  bounced: 5,
  open_rate: 53.3,
  reply_rate: 13.3,
  click_rate: 6.7,
  bounce_rate: 3.3,
  time_series: { labels: ['2024-01-01'], sent: [10], opened: [5], replied: [2] },
  campaign_stats: [],
  recent_activity: [
    { type: 'lead_active', description: 'test@acme.test — active in Campaign A', time: new Date().toISOString() },
  ],
};

test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await seedAuthTokens(page);
  });

  test('KPI cards render with correct values', async ({ page, mockApi }) => {
    await mockApi('**/api/v1/analytics/dashboard/**', MOCK_DASHBOARD);
    await mockApi('**/api/v1/campaigns/**', { results: [], count: 0 });

    await page.goto('/dashboard.html');

    await expect(page.locator('#total-leads-count')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('#total-leads-count')).toHaveText('42');
    await expect(page.locator('#active-campaigns-count')).toHaveText('3');
    await expect(page.locator('#emails-sent-count')).toHaveText('150');
    await expect(page.locator('#reply-rate')).toContainText('13.3');
  });

  test('recent activity renders', async ({ page, mockApi }) => {
    await mockApi('**/api/v1/analytics/dashboard/**', MOCK_DASHBOARD);
    await mockApi('**/api/v1/campaigns/**', { results: [], count: 0 });

    await page.goto('/dashboard.html');

    await expect(page.locator('#activity-list')).toBeVisible({ timeout: 10000 });
  });

  test('unauthenticated user is redirected to login when API returns 401', async ({ page, mockApi }) => {
    await page.addInitScript(() => window.localStorage.clear());

    // Return 401 on all API calls to trigger the redirect logic in api.js
    await mockApi('**/api/v1/**', { detail: 'Unauthorized' }, { status: 401 });

    await page.goto('/dashboard.html');

    await expect(page).toHaveURL(/login\.html/, { timeout: 10000 });
  });
});
