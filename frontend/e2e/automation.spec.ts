import fs from 'node:fs';
import path from 'node:path';

import { expect, test } from '@playwright/test';

// Runs after app.spec.ts, which set up the library, the fake Usenet indexer, SABnzbd and the
// remote path mapping. Automation runs in fast-forward here (see e2e/serve.sh).

const pad = (n: number) => String(n).padStart(2, '0');
const monthKey = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;

test('Phase 5 definition of done: a newly posted issue of a monitored magazine is grabbed on its own', async ({
  page,
  request,
}) => {
  const fake = `http://127.0.0.1:${process.env.E2E_PROWLARR_PORT}`;
  const { apiKey } = (await (await request.get('/initialize.json')).json()) as { apiKey: string };
  const headers = { 'X-Api-Key': apiKey };

  // Setup: earlier tests left National Geographic with wanted issues the fake indexer always
  // offers; unmonitor it so only Wired is in play. Wired is monthly and monitored, and its
  // only issue so far is last month's.
  const [nationalGeographic] = (await (await request.get('/api/v1/magazine', { headers })).json()) as { id: number }[];
  await request.patch(`/api/v1/magazine/${nationalGeographic!.id}`, { headers, data: { monitored: false } });
  const now = new Date();
  const lastMonth = monthKey(new Date(now.getFullYear(), now.getMonth() - 1, 1));
  const thisMonth = monthKey(now);
  const wired = (await (
    await request.post('/api/v1/magazine', { headers, data: { title: 'Wired', frequency: 'monthly', monitored: true } })
  ).json()) as { id: number };
  await request.post('/api/v1/issue', {
    headers,
    data: { magazineId: wired.id, issueNumber: lastMonth, publishDate: `${lastMonth}-01`, monitored: false },
  });

  // The e2e setup paused automation; switch it on as a user would.
  await page.goto('/settings/automation');
  await expect(page.getByText('Automation is paused')).toBeVisible();
  await page.getByText('Automatic searching and grabbing', { exact: true }).click();
  await page.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByText('Automation is paused')).toBeHidden();

  // From here on, nobody touches Magarr. First it adds this month's issue as wanted...
  await page.goto('/wanted');
  const wanted = page.getByTestId('wanted-row').filter({ hasText: 'Wired' }).filter({ hasText: thisMonth });
  await expect(async () => {
    await page.reload();
    await expect(wanted).toBeVisible({ timeout: 1000 });
  }).toPass({ timeout: 30_000 });

  // ...then the issue is posted to the indexer, and RSS sync grabs it; it downloads and imports.
  const release = `Wired.${thisMonth.replace('-', '.')}.PDF`;
  expect((await request.post(`${fake}/control/post?title=${release}`)).ok()).toBe(true);
  await page.goto(`/magazine/${wired.id}`);
  const issue = page.getByTestId('issue-row').filter({ hasText: thisMonth });
  await expect(async () => {
    await page.reload();
    await expect(issue.getByText('Downloaded')).toBeVisible({ timeout: 1000 });
  }).toPass({ timeout: 60_000 });

  const file = path.join(process.env.E2E_DIR!, 'library', 'Wired', `Wired - ${thisMonth} - Issue ${thisMonth}.pdf`);
  expect(fs.readFileSync(file, 'utf8')).toContain('fake magazine');

  await page.goto('/activity/history');
  const grabbed = page.getByTestId('history-row').filter({ hasText: release }).filter({ hasText: 'Grabbed' });
  await expect(grabbed).toContainText('RSS sync');

  // The calendar shows it too.
  await page.goto('/calendar');
  await expect(page.getByTestId(`calendar-day-${thisMonth}-01`).getByText(`Wired · ${thisMonth}`)).toBeVisible();
});
