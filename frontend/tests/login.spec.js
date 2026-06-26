// @ts-check
const { test, expect } = require('./fixtures');

test.describe('Login flow', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => window.localStorage.clear());
  });

  test('user can log in with valid credentials and reach the dashboard', async ({ page, mockApi }) => {
    await mockApi('**/api/v1/token/', {
      access: 'mock-access-token',
      refresh: 'mock-refresh-token',
    }, { method: 'POST', status: 200 });

    await mockApi('**/api/v1/analytics/dashboard/**', {
      total_leads: 0,
      active_campaigns: 0,
      emails_sent: 0,
      opened: 0,
      replied: 0,
      clicked: 0,
      bounced: 0,
      open_rate: 0,
      reply_rate: 0,
      click_rate: 0,
      bounce_rate: 0,
      time_series: { labels: [], sent: [], opened: [], replied: [] },
      campaign_stats: [],
      recent_activity: [],
    });

    await page.goto('/login.html');

    await page.locator('#floatingInput').fill('owner@acme.test');
    await page.locator('#floatingPassword').fill('StrongPass123!');
    await page.getByRole('button', { name: /sign in/i }).click();

    await expect(page).toHaveURL(/dashboard\.html/, { timeout: 10000 });
  });

  test('invalid credentials show an error and keep the user on the login page', async ({ page, mockApi }) => {
    await mockApi('**/api/v1/token/', { detail: 'No active account found with the given credentials' }, {
      method: 'POST',
      status: 401,
    });

    await page.goto('/login.html');

    let alertMessage = '';
    page.once('dialog', async (dialog) => {
      alertMessage = dialog.message();
      await dialog.accept();
    });

    await page.locator('#floatingInput').fill('wrong@acme.test');
    await page.locator('#floatingPassword').fill('WrongPassword!');
    await page.getByRole('button', { name: /sign in/i }).click();

    await expect.poll(() => alertMessage).toContain('Login failed');
    await expect(page).toHaveURL(/login\.html/);
  });
});
