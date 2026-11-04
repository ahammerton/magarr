import fs from 'node:fs';
import path from 'node:path';

import { expect, type Page, test } from '@playwright/test';

const LIBRARY = path.join(process.env.E2E_DIR!, 'library');
const SHOTS = process.env.E2E_SCREENSHOTS;

/** Optional screenshots for manual review; waits out Mantine's transitions first. */
async function snap(page: Page, name: string, fullPage = false): Promise<void> {
  if (!SHOTS) return;
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage });
}

test('Phase 1 definition of done: add, generate 24 monthly issues, mark 6 wanted', async ({ page }) => {
  // A root folder is required before adding magazines.
  await page.goto('/settings/mediamanagement');
  await page.getByLabel('Add a root folder').fill(LIBRARY);
  await page.getByRole('button', { name: 'Add', exact: true }).click();
  await expect(page.getByText(LIBRARY, { exact: true })).toBeVisible();

  // Add magazine wizard.
  await page.goto('/library/add');
  await page.getByRole('textbox', { name: /^Title/ }).fill('National Geographic');
  const altTitles = page.getByRole('textbox', { name: 'Alternate titles' });
  await altTitles.fill('Nat Geo');
  await altTitles.press('Enter');
  await page.getByRole('button', { name: 'Next' }).click();
  await expect(page.getByRole('textbox', { name: 'Root folder' })).toHaveValue(LIBRARY);
  await expect(page.getByRole('textbox', { name: 'Quality profile' })).toHaveValue('Any');
  await snap(page, 'wizard-settings');
  await page.getByRole('button', { name: 'Next' }).click();
  await page.getByRole('button', { name: 'Add magazine' }).click();

  await expect(page.getByRole('heading', { name: 'National Geographic' })).toBeVisible();
  await expect(page).toHaveURL(/\/magazine\/\d+$/);

  // Generate 24 monthly issues.
  await page.getByRole('button', { name: 'Generate issues' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('First issue date').fill('2025-01-01');
  await dialog.getByLabel('Number of issues').fill('24');
  await dialog.getByRole('button', { name: 'Generate' }).click();
  await expect(page.getByText('Created 24 issue(s), skipped 0 existing')).toBeVisible();
  await expect(page.getByTestId('issue-row')).toHaveCount(24);

  // Select six issues and mark them wanted.
  for (const month of ['01', '02', '03', '04', '05', '06']) {
    await page.getByLabel(`Select issue 2025-${month}`).check();
  }
  await expect(page.getByText('6 selected')).toBeVisible();
  await page.getByRole('button', { name: 'Mark wanted' }).click();
  await expect(page.getByText('Wanted (6)')).toBeVisible();
  await expect(page.getByText('6 selected')).toBeHidden();
  await snap(page, 'detail-wanted', true);

  // It's persisted, not just client state.
  await page.reload();
  await expect(page.getByText('Wanted (6)')).toBeVisible();
  await expect(page.getByText('Missing (18)')).toBeVisible();

  // With no indexers yet, search points to the indexer settings.
  await page.getByLabel('Search for issue 2025-01').click();
  await expect(page.getByText('No indexers', { exact: true })).toBeVisible();
  await page.keyboard.press('Escape');

  // Library shows the magazine with its counts.
  await page.goto('/library');
  const card = page.getByTestId('magazine-card');
  await expect(card).toHaveCount(1);
  await expect(card.getByText('0/24')).toBeVisible();
  await snap(page, 'library');
});

test('Phase 0 smoke: system status page', async ({ page }) => {
  await page.goto('/system/status');
  await expect(page.getByRole('heading', { name: 'Status' })).toBeVisible();
  // Any applied revision (hardcoding the number broke on every new migration).
  await expect(page.getByRole('row', { name: /Database migration/ })).toContainText(/\d{4}/);
});

test('sidebar sections navigate when clicked', async ({ page }) => {
  await page.goto('/system/status');
  const nav = page.getByRole('navigation', { name: 'Main' });
  for (const [section, heading] of [
    ['Library', 'Magazines'],
    ['Settings', 'Media Management'],
    ['System', 'Status'],
    ['Library', 'Magazines'],
  ] as const) {
    await nav.getByText(section, { exact: true }).click();
    await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible();
  }
  // Sub-pages still work, and the open section stays expanded.
  await nav.getByText('Settings', { exact: true }).click();
  await nav.getByText('Profiles', { exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Profiles', exact: true })).toBeVisible();
});

test('Phase 2 definition of done: search a wanted issue via Prowlarr, parsed and sortable', async ({ page }) => {
  // Runs after the Phase 1 test, which created National Geographic with issue 2025-01 wanted.
  await page.goto('/settings/indexers');
  await page.getByLabel('Prowlarr URL').fill(`http://127.0.0.1:${process.env.E2E_PROWLARR_PORT}`);
  await page.getByRole('textbox', { name: 'API key' }).first().fill('e2e-prowlarr-key');
  await page.getByRole('button', { name: 'Test', exact: true }).first().click();
  await expect(page.getByText('Connected to Prowlarr 1.99.0-fake')).toBeVisible();
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await page.getByRole('button', { name: 'Sync indexers' }).click();
  await expect(page.getByText('Added: Fake Tracker (Prowlarr)')).toBeVisible();
  const row = page.getByTestId('indexer-row');
  await expect(row).toHaveCount(1);
  await row.getByLabel('Test Fake Tracker (Prowlarr)').click();
  await expect(row.getByText('OK', { exact: true })).toBeVisible();
  await snap(page, 'indexers');

  await page.goto('/library');
  await page.getByTestId('magazine-card').click();
  await page.getByLabel('Search for issue 2025-01').click();
  const dialog = page.getByRole('dialog');
  const rows = dialog.getByTestId('release-row');
  await expect(rows).toHaveCount(3);
  await expect(dialog.getByText(/3 release\(s\), 1 matching this issue/)).toBeVisible();
  // Approved release first, with its parsed issue, quality and peers.
  await expect(rows.first()).toContainText('National Geographic UK - January 2025 (HQ PDF)');
  await expect(rows.first()).toContainText('2025-01');
  await expect(rows.first()).toContainText('PDF (Hi-Res)');
  await expect(rows.first()).toContainText('42/8');
  await expect(dialog.getByLabel('Multi-issue pack (grab it manually to import every issue in it)')).toBeVisible();

  // Sortable: biggest first on the first click.
  await dialog.getByRole('button', { name: 'Size' }).click();
  await expect(rows.first()).toContainText('National Geographic Complete Year 2024');
  await dialog.getByRole('button', { name: 'Size' }).click();
  await expect(rows.first()).toContainText('National Geographic Traveller UK');
  await snap(page, 'search');
});

test('Phase 3 definition of done: grab to SABnzbd, track to ready-for-import', async ({ page }) => {
  // Runs after the Phase 1 test, which created National Geographic with issue 2025-01 wanted.
  const fake = `http://127.0.0.1:${process.env.E2E_PROWLARR_PORT}`;

  await page.goto('/settings/downloadclients');
  await page.getByRole('button', { name: 'Add download client' }).click();
  const client = page.getByRole('dialog');
  await client.getByRole('textbox', { name: /^Host/ }).fill('127.0.0.1');
  await client.getByRole('textbox', { name: /^Port/ }).fill(String(process.env.E2E_PROWLARR_PORT));
  await client.getByRole('textbox', { name: /^Url base/ }).fill('/sabnzbd');
  await client.getByLabel(/^API key/).fill('e2e-prowlarr-key');
  await client.getByRole('button', { name: 'Test' }).click();
  await expect(client.getByText('Connected to SABnzbd 4.9.9-fake')).toBeVisible();
  await client.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByTestId('client-row')).toHaveCount(1);

  await page.goto('/settings/indexers');
  await page.getByRole('button', { name: 'Add indexer' }).click();
  const indexer = page.getByRole('dialog');
  await indexer.getByRole('textbox', { name: /^Name/ }).fill('Fake Usenet');
  await indexer.getByRole('textbox', { name: /^URL/ }).fill(`${fake}/usenet`);
  await indexer.getByLabel('API key').fill('e2e');
  await indexer.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByTestId('indexer-row')).toHaveCount(2);

  await page.goto('/library');
  await page.getByTestId('magazine-card').click();
  await page.getByLabel('Search for issue 2025-01').click();
  const search = page.getByRole('dialog');
  const release = search.getByTestId('release-row').filter({ hasText: 'National.Geographic.2025.01.True.PDF' });
  await expect(release).toHaveCount(1);
  await release.getByRole('button', { name: /^Grab/ }).click();
  await expect(release.getByText('Grabbed')).toBeVisible();
  await snap(page, 'grab');
  await page.keyboard.press('Escape');

  const row = page.getByTestId('issue-row').filter({ hasText: '2025-01' });
  await expect(row.getByText(/Queued|Downloading/)).toBeVisible();
  await expect(row.getByText('Ready to import')).toBeVisible({ timeout: 30_000 });
  await snap(page, 'pending-import');
});

test('Phase 4 definition of done: the download imports into the library, renamed', async ({ page }) => {
  // Continues from Phase 3: the 2025-01 download is "Ready to import", but Magarr can't see
  // SABnzbd's /data/usenet/complete until a remote path mapping says where it is.
  const nas = path.join(process.env.E2E_DIR!, 'nas');
  await page.goto('/activity/queue');
  const queued = page.getByTestId('queue-row');
  await expect(queued).toHaveCount(1);
  await expect(queued).toContainText('Add a remote path mapping');

  await page.goto('/settings/downloadclients');
  await page.getByRole('textbox', { name: 'Client host' }).fill('127.0.0.1');
  await page.getByLabel("Client's path").fill('/data');
  await page.getByLabel("Magarr's path").fill(nas);
  const mappings = page.locator('.mantine-Card-root', { has: page.getByRole('heading', { name: 'Remote path mappings' }) });
  await mappings.getByRole('button', { name: 'Add' }).click();
  await expect(page.getByTestId('mapping-row')).toHaveCount(1);

  // The poller retries pending imports on its own (every second in this test).
  await page.goto('/activity/queue');
  await expect(page.getByText('Nothing is downloading or waiting to be imported.')).toBeVisible({ timeout: 20_000 });

  await page.goto('/library');
  await page.getByTestId('magazine-card').click();
  const row = page.getByTestId('issue-row').filter({ hasText: '2025-01' });
  await expect(row.getByText('Downloaded')).toBeVisible();
  await snap(page, 'imported');

  const imported = path.join(
    process.env.E2E_DIR!,
    'library',
    'National Geographic',
    'National Geographic - 2025-01 - Issue 2025-01.pdf',
  );
  expect(fs.readFileSync(imported, 'utf8')).toContain('fake magazine');
  // Moved out of the download folder, and the junk-only folder cleaned up.
  expect(fs.existsSync(path.join(nas, 'usenet', 'complete', 'National.Geographic.2025.01.True.PDF'))).toBe(false);

  await page.goto('/activity/history');
  await expect(page.getByTestId('history-row').first()).toContainText('Imported');
});
