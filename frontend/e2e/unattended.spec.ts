import fs from 'node:fs';
import path from 'node:path';

import { expect, test } from '@playwright/test';

// Phase 6 definition of done: the whole stack runs, and reports to Discord, without anyone
// opening the UI. Everything here goes through the API (what a setup script or another app
// would do); no page is loaded. Runs after the other specs, which set up the library, Prowlarr,
// SABnzbd and the remote path mapping. Automation runs in fast-forward (see e2e/serve.sh).

const pad = (n: number) => String(n).padStart(2, '0');
const monthKey = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}`;

interface DiscordMessage {
  username: string;
  embeds: { title: string; description?: string }[];
}

test('Phase 6 definition of done: runs unattended and reports to Discord, without the UI', async ({ request }) => {
  const fake = `http://127.0.0.1:${process.env.E2E_PROWLARR_PORT}`;
  const { apiKey } = (await (await request.get('/initialize.json')).json()) as { apiKey: string };
  const headers = { 'X-Api-Key': apiKey };
  const api = async (method: 'get' | 'post' | 'put' | 'patch', url: string, data?: unknown) => {
    const response = await request[method](url, { headers, data });
    expect(response.ok(), `${method.toUpperCase()} ${url}: ${await response.text()}`).toBe(true);
    return response.status() === 204 ? null : response.json();
  };

  // One-time setup, by API: a Discord notification and a monitored monthly magazine whose
  // latest issue is last month's. Automation on (the e2e setup paused it).
  const discord = await api('post', '/api/v1/notification', {
    name: 'Discord',
    implementation: 'discord',
    events: ['grab', 'import', 'failure'],
    settings: { webhookUrl: `${fake}/api/webhooks/1/e2e-token` },
  });
  expect((await api('post', `/api/v1/notification/${discord.id}/test`)).ok).toBe(true);
  const automation = await api('get', '/api/v1/config/automation');
  delete automation.jobs;
  await api('put', '/api/v1/config/automation', { ...automation, monitoringEnabled: true });

  const now = new Date();
  const lastMonth = monthKey(new Date(now.getFullYear(), now.getMonth() - 1, 1));
  const thisMonth = monthKey(now);
  const edge = await api('post', '/api/v1/magazine', { title: 'Edge', frequency: 'monthly', monitored: true });
  await api('post', '/api/v1/issue', {
    magazineId: edge.id,
    issueNumber: lastMonth,
    publishDate: `${lastMonth}-01`,
    monitored: false,
  });

  // From here nothing touches Magarr. A new issue appears on the indexer...
  const release = `Edge.${thisMonth.replace('-', '.')}.PDF`;
  const wanted = async () =>
    ((await api('get', `/api/v1/issue?magazineId=${edge.id}`)) as { issueNumber: string; status: string }[]).find(
      (i) => i.issueNumber === thisMonth,
    )?.status;
  await expect.poll(wanted, { timeout: 30_000 }).toBe('wanted'); // added by the schedule
  await request.post(`${fake}/control/post?title=${release}`);

  // ...and Discord hears that it was grabbed and then imported.
  const titles = async () =>
    ((await (await request.get(`${fake}/control/discord`)).json()) as DiscordMessage[]).map((m) => m.embeds[0]!.title);
  await expect
    .poll(titles, { timeout: 60_000 })
    .toEqual(expect.arrayContaining([`Grabbed Edge ${thisMonth}`, `Imported Edge ${thisMonth}`]));

  const messages = (await (await request.get(`${fake}/control/discord`)).json()) as DiscordMessage[];
  const grab = messages.find((m) => m.embeds[0]!.title === `Grabbed Edge ${thisMonth}`)!;
  expect(grab.username).toBe('Magarr');
  expect(grab.embeds[0]!.description).toContain(`${release}\nSent to SABnzbd (RSS sync)`);
  expect(messages[0]!.embeds[0]!.title).toBe('Test from Magarr');

  const file = path.join(process.env.E2E_DIR!, 'library', 'Edge', `Edge - ${thisMonth} - Issue ${thisMonth}.pdf`);
  expect(fs.readFileSync(file, 'utf8')).toContain('fake magazine');
  expect(await wanted()).toBe('downloaded');
});
