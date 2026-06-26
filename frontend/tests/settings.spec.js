// @ts-check
const { test, expect, seedAuthTokens } = require('./fixtures');

const MOCK_PROFILE = {
  id: 'user-001',
  email: 'owner@acme.test',
  role: 'ADMIN',
  organization: {
    id: 'org-001',
    name: 'Acme Corp',
  },
};

const MOCK_CONNECTED_ACCOUNTS = [];

test.describe('Settings page', () => {
  test.beforeEach(async ({ page }) => {
    await seedAuthTokens(page);
  });

  test('settings page loads with profile data', async ({ page, mockApi }) => {
    await mockApi('**/api/v1/auth/me/**', MOCK_PROFILE);
    await mockApi('**/api/v1/connected-accounts/**', MOCK_CONNECTED_ACCOUNTS);

    await page.goto('/settings.html');

    await expect(page.locator('#profile-email')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('#profile-email')).toHaveValue('owner@acme.test');
    await expect(page.locator('#org-name')).toHaveValue('Acme Corp');
  });

  test('save profile button is visible', async ({ page, mockApi }) => {
    await mockApi('**/api/v1/auth/me/**', MOCK_PROFILE);
    await mockApi('**/api/v1/connected-accounts/**', MOCK_CONNECTED_ACCOUNTS);

    await page.goto('/settings.html');

    await expect(page.locator('#save-profile-btn')).toBeVisible({ timeout: 10000 });
  });

  test('Google connect button is visible', async ({ page, mockApi }) => {
    await mockApi('**/api/v1/auth/me/**', MOCK_PROFILE);
    await mockApi('**/api/v1/connected-accounts/**', MOCK_CONNECTED_ACCOUNTS);

    await page.goto('/settings.html');

    await expect(page.locator('#google-connect-btn')).toBeVisible({ timeout: 10000 });
  });

  test('dark mode toggle is present and clickable', async ({ page, mockApi }) => {
    await mockApi('**/api/v1/auth/me/**', MOCK_PROFILE);
    await mockApi('**/api/v1/connected-accounts/**', MOCK_CONNECTED_ACCOUNTS);

    await page.goto('/settings.html');

    const toggle = page.locator('#theme-toggle');
    await expect(toggle).toBeVisible({ timeout: 10000 });

    const initialState = await toggle.isChecked();
    await toggle.click();
    const newState = await toggle.isChecked();
    expect(newState).not.toBe(initialState);
  });

  test('AI personalization checkbox is present', async ({ page, mockApi }) => {
    await mockApi('**/api/v1/auth/me/**', MOCK_PROFILE);
    await mockApi('**/api/v1/connected-accounts/**', MOCK_CONNECTED_ACCOUNTS);

    await page.goto('/settings.html');

    await expect(page.locator('#enable-ai-personalization')).toBeVisible({ timeout: 10000 });
  });
});
