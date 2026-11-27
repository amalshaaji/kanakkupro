import { readFile } from 'node:fs/promises';
import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const password = process.env.PILOT_REVIEW_PASSWORD;
if (!password || password.length < 16) throw new Error('Set an ephemeral review password.');

async function login(page, email = 'owner-a@pilot.example.test') {
  await page.goto('/accounts/login/');
  await page.getByRole('textbox', { name: 'Email:', exact: true }).fill(email);
  await page.getByRole('textbox', { name: 'Password:', exact: true }).fill(password);
  await page.getByRole('button', { name: 'Sign In', exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard\/$/);
}

async function audit(page, info, label, assertClean = true) {
  const result = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze();
  await info.attach(`accessibility-${label}`, {
    body: JSON.stringify(result.violations, null, 2), contentType: 'application/json',
  });
  const findings = result.violations.map(violation => ({
    page: label, rule: violation.id,
    nodes: violation.nodes.map(node => ({ target: node.target, issue: node.failureSummary })),
  }));
  if (assertClean) expect(findings, `${label}: automated accessibility violations`).toEqual([]);
  return findings;
}

test.beforeEach(async ({ page, baseURL }) => {
  await page.route('**/*', route => {
    if (new URL(route.request().url()).origin === new URL(baseURL).origin) return route.continue();
    return route.abort();
  });
});

test('keyboard skip link and login page accessibility', async ({ page }, info) => {
  await page.goto('/accounts/login/');
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link', { name: 'Skip to main content', exact: true })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('#main-content')).toBeFocused();
  await audit(page, info, 'login');
});

test('owner screens have labels, contrast and bounded layouts', async ({ page }, info) => {
  await login(page);
  const paths = [
    '/dashboard/', '/customers/', '/customers/new/', '/catalog/', '/catalog/new/',
    '/invoices/', '/invoices/new/', '/invoices/settings/', '/reports/financial/',
    '/dashboard/pilot/', '/tenants/team/',
  ];
  const findings = [];
  for (const path of paths) {
    const response = await page.goto(path);
    expect(response.status()).toBe(200);
    await expect(page.getByRole('main')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    findings.push(...await audit(page, info, path.replaceAll('/', '-'), false));
  }
  expect(findings, 'Accessibility findings across all owner screens').toEqual([]);
});

test('login errors remain labelled and readable', async ({ page }, info) => {
  await page.goto('/accounts/login/');
  await page.getByRole('textbox', { name: 'Email:', exact: true }).fill('no-such-user@pilot.example.test');
  await page.getByRole('textbox', { name: 'Password:', exact: true }).fill('Invalid-Review-Password-Only-61!');
  await page.getByRole('button', { name: 'Sign In', exact: true }).click();
  await expect(page).toHaveURL(/\/accounts\/login\/$/);
  await expect(page.locator('.errorlist')).toBeVisible();
  await audit(page, info, 'login-error');
});

test('owner issues an invoice, records partial and final payments and downloads PDF', async ({ page }) => {
  await login(page);
  await page.goto('/invoices/new/');
  await page.locator('select[name="customer"]').selectOption({ label: 'Review A customer 000' });
  await page.locator('select[name="buyer_state"]').selectOption('27');
  await page.locator('select[name="place_of_supply"]').selectOption('27');
  await page.locator('textarea[name="delivery_address"]').fill('12 Synthetic Road, Mumbai 400001');
  await page.locator('input[name="supported_supply"]').check();
  await page.locator('select[name="lines-0-item"]').selectOption({ label: 'Review A service 00' });
  await page.locator('input[name="lines-0-description"]').fill('Browser pilot acceptance');
  await page.locator('input[name="lines-0-quantity"]').fill('1');
  await page.locator('input[name="lines-0-unit_price"]').fill('100');
  await page.getByRole('button', { name: 'Save draft', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Issue invoice', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Issue invoice', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Edit draft', exact: true })).toHaveCount(0);
  const invoiceURL = page.url();
  for (const amount of ['50', '68']) {
    await page.locator('summary').filter({ hasText: 'Record payment' }).click();
    await page.locator('input[name="amount"]').fill(amount);
    await page.getByRole('button', { name: 'Save payment', exact: true }).click();
    if (amount === '50') await expect(page.getByText('Partially paid', { exact: true })).toBeVisible();
  }
  await expect(page.getByText('Paid', { exact: true })).toBeVisible();
  expect(await page.getByRole('main').innerText()).toMatch(/Net payments\s+118\.00\s+Outstanding\s+0\.00/);
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Download PDF', exact: true }).click();
  const download = await downloadPromise;
  expect((await readFile(await download.path())).subarray(0, 4).toString()).toBe('%PDF');
  const menu = page.locator('summary[aria-label="Open account and business menu"]');
  if (await menu.isVisible()) await menu.press('Enter');
  await page.getByRole('button', { name: 'Sign out', exact: true }).filter({ visible: true }).click();
  await login(page, 'owner-b@pilot.example.test');
  const foreign = await page.goto(invoiceURL);
  expect(foreign.status()).toBe(404);
  await expect(page.getByText('Browser pilot acceptance', { exact: true })).toHaveCount(0);
});

test('viewer cannot create invoices or access the owner pilot guide', async ({ page }) => {
  await login(page, 'viewer@pilot.example.test');
  expect((await page.goto('/invoices/new/')).status()).toBe(403);
  expect((await page.goto('/dashboard/pilot/')).status()).toBe(403);
});

test('mobile menu opens from the keyboard and reaches workspace links', async ({ page }, info) => {
  test.skip(info.project.name !== 'mobile', 'Mobile navigation only');
  await login(page);
  const menu = page.locator('summary[aria-label="Open account and business menu"]');
  await menu.press('Enter');
  await expect(page.getByRole('link', { name: 'Overview', exact: true })).toBeVisible();
  await menu.press('Tab');
  await expect(page.getByRole('link', { name: 'Overview', exact: true })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/\/dashboard\/$/);
});
