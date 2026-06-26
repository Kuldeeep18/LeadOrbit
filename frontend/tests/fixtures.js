// @ts-check
const { test: base, expect } = require('@playwright/test');

const MOCK_TOKENS = {
  access: 'mock-access-token',
  refresh: 'mock-refresh-token',
};

async function seedAuthTokens(page) {
  await page.addInitScript((tokens) => {
    window.localStorage.setItem('access_token', tokens.access);
    window.localStorage.setItem('refresh_token', tokens.refresh);
  }, MOCK_TOKENS);
}

async function clearAuthTokens(page) {
  await page.addInitScript(() => {
    window.localStorage.clear();
  });
}

const test = base.extend({
  mockApi: async ({ page }, use) => {
    const mock = async (urlPattern, response, options = {}) => {
      const { method = null, status = 200 } = options;
      await page.route(urlPattern, async (route) => {
        const request = route.request();
        if (method && request.method() !== method) {
          return route.continue();
        }
        await route.fulfill({
          status,
          contentType: 'application/json',
          body: JSON.stringify(response),
        });
      });
    };
    await use(mock);
  },

  authenticatedPage: async ({ page }, use) => {
    await seedAuthTokens(page);
    await use(page);
  },
});

module.exports = { test, expect, MOCK_TOKENS, seedAuthTokens, clearAuthTokens };
