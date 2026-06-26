// @ts-check
const { test, expect } = require('./fixtures');

test.describe('Registration flow', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => window.localStorage.clear());
  });

  test('user can register and is redirected to dashboard', async ({ page, mockApi }) => {
    await mockApi('**/api/v1/auth/register/', {
      access: 'mock-access-token',
      refresh: 'mock-refresh-token',
    }, { method: 'POST', status: 201 });

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

    await page.goto('/register.html');

    await page.locator('#firstName').fill('Test');
    await page.locator('#lastName').fill('User');
    await page.locator('#emailAddress').fill('testuser@acme.test');
    await page.locator('#password').fill('StrongPass123!');
    await page.getByRole('button', { name: /create account|sign up|register/i }).click();

    await expect(page).toHaveURL(/dashboard\.html/, { timeout: 10000 });
  });

  test('registration failure shows error and stays on register page', async ({ page, mockApi }) => {
    await mockApi('**/api/v1/auth/register/', {
      email: ['A user with this email already exists.'],
    }, { method: 'POST', status: 400 });

    await page.goto('/register.html');

    let alertMessage = '';
    page.once('dialog', async (dialog) => {
      alertMessage = dialog.message();
      await dialog.accept();
    });

    await page.locator('#firstName').fill('Test');
    await page.locator('#lastName').fill('User');
    await page.locator('#emailAddress').fill('existing@acme.test');
    await page.locator('#password').fill('StrongPass123!');
    await page.getByRole('button', { name: /create account|sign up|register/i }).click();

    await expect.poll(() => alertMessage, { timeout: 5000 }).toBeTruthy();
    await expect(page).toHaveURL(/register\.html/);
  });

  test('register page has all required fields', async ({ page }) => {
    await page.goto('/register.html');

    await expect(page.locator('#firstName')).toBeVisible();
    await expect(page.locator('#lastName')).toBeVisible();
    await expect(page.locator('#emailAddress')).toBeVisible();
    await expect(page.locator('#password')).toBeVisible();
    await expect(page.getByRole('button', { name: /create account|sign up|register/i })).toBeVisible();
  });
});
