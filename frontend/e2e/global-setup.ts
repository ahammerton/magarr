/**
 * Runs once the servers are up. Automation (RSS sync, backlog search) runs in fast-forward in
 * e2e, and the fake indexer answers every search, so it would grab issues the earlier phase
 * tests grab by hand. Switch it off; the Phase 5 test turns it back on in the UI.
 */
export default async function globalSetup(): Promise<void> {
  const base = `http://localhost:${process.env.E2E_PORT ?? 8383}`;
  const { apiKey } = (await (await fetch(`${base}/initialize.json`)).json()) as { apiKey: string };
  const headers = { 'X-Api-Key': apiKey, 'Content-Type': 'application/json' };
  const current = (await (await fetch(`${base}/api/v1/config/automation`, { headers })).json()) as Record<string, unknown>;
  delete current.jobs;
  const saved = await fetch(`${base}/api/v1/config/automation`, {
    method: 'PUT',
    headers,
    body: JSON.stringify({ ...current, monitoringEnabled: false }),
  });
  if (!saved.ok) throw new Error(`Could not pause automation: ${saved.status}`);
}
