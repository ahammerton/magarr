import { http, HttpResponse, ws } from 'msw';

import type { SystemStatus } from '../api/system';
import type {
  Download,
  DownloadClient,
  HistoryRecord,
  ManualImportScan,
  MediaSettings,
  RemotePathMapping,
  Indexer,
  Issue,
  Magazine,
  NamingConfig,
  ProwlarrConfig,
  QualityProfile,
  Release,
  RootFolder,
  SearchResult,
  Automation,
  AutomationSettings,
  Backup,
  Health,
  LogEntry,
  Notification,
  Task,
  TaskRun,
  DownloadSettings,
  MagazineIssue,
} from '../api/types';

export const TEST_API_KEY = 'test-api-key';

/** The live queue socket (MSW intercepts WebSockets). Tests read the URL and push messages. */
const queueSocket = ws.link('ws://*/api/v1/ws/queue');
export interface QueueSocketClient {
  url: URL;
  send(data: string): void;
}
const live = globalThis as unknown as { __queueClients?: QueueSocketClient[] };
export function queueClients(): QueueSocketClient[] {
  return (live.__queueClients ??= []);
}

export const statusFixture: SystemStatus = {
  appName: 'Magarr',
  version: '0.1.0',
  startTime: '2026-10-15T09:00:00Z',
  uptimeSeconds: 3725,
  isDocker: true,
  osName: 'Linux',
  osVersion: '6.8.0',
  pythonVersion: '3.12.7',
  databaseType: 'sqlite',
  databaseVersion: '3.46.1',
  databaseMigration: '0002',
  appDataDir: '/config',
  authentication: 'apiKey',
};

const stats = (issueCount = 0, downloadedCount = 0, wantedCount = 0, sizeOnDisk = 0) => ({
  issueCount,
  downloadedCount,
  wantedCount,
  sizeOnDisk,
});

export function makeMagazine(overrides: Partial<Magazine> = {}): Magazine {
  return {
    id: 1,
    title: 'National Geographic',
    sortTitle: 'national geographic',
    alternateTitles: ['Nat Geo'],
    publisher: 'NG Partners',
    language: 'en',
    category: 'Science',
    frequency: 'monthly',
    firstIssueYear: 1888,
    tags: ['science'],
    qualityProfileId: 1,
    rootFolderId: 1,
    folder: 'National Geographic (1888)',
    path: '/magazines/National Geographic (1888)',
    monitored: true,
    posterUrl: null,
    searchCutoff: null,
    grabNewSpecials: false,
    coverUrl: null,
    issueNamingTemplate: null,
    notes: null,
    added: '2026-10-15T09:00:00Z',
    statistics: stats(3, 1, 1, 52_428_800),
    ...overrides,
  };
}

export function makeIndexer(overrides: Partial<Indexer> = {}): Indexer {
  return {
    id: 1,
    name: 'Usenet',
    implementation: 'newznab',
    protocol: 'usenet',
    baseUrl: 'https://nzb.example/',
    apiPath: '/api',
    apiKey: '********',
    categories: [7010],
    priority: 25,
    enabled: true,
    tags: [],
    requestInterval: 2,
    source: 'manual',
    prowlarrId: null,
    supportedCategories: [],
    consecutiveFailures: 0,
    disabledUntil: null,
    lastError: null,
    lastSuccess: '2026-10-15T09:00:00Z',
    ...overrides,
  };
}

export function makeDownload(overrides: Partial<Download> = {}): Download {
  return {
    id: 1,
    issueId: 3,
    magazineId: 1,
    magazineTitle: 'National Geographic',
    issueNumber: '2024-07',
    downloadClientId: 1,
    title: 'x',
    protocol: 'usenet',
    status: 'queued',
    progress: 0,
    size: 52_428_800,
    sizeLeft: 0,
    outputPath: null,
    message: null,
    added: '2026-10-21T09:00:00Z',
    completedAt: null,
    ...overrides,
  };
}

export function makeIssue(overrides: Partial<Issue> = {}): Issue {
  return {
    id: 1,
    magazineId: 1,
    issueNumber: '2024-05',
    sortIndex: 20240500,
    title: null,
    publishDate: '2024-05-01',
    coverUrl: null,
    monitored: false,
    status: 'missing',
    lastSearchedAt: null,
    file: null,
    download: null,
    ...overrides,
  };
}

/** Mutable fake backend state, reset before every test. */
export const db = {
  magazines: [] as Magazine[],
  issues: [] as Issue[],
  rootFolders: [] as RootFolder[],
  profiles: [] as QualityProfile[],
  naming: {} as NamingConfig,
  indexers: [] as Indexer[],
  prowlarr: { url: '', apiKey: '', lastSync: null } as ProwlarrConfig,
  search: { queries: [], indexers: [], releases: [] } as SearchResult,
  downloadClients: [] as DownloadClient[],
  downloadSettings: { redownloadFailed: true, maxRetries: 3 } as DownloadSettings,
  automation: {} as Automation,
  notifications: [] as Notification[],
  tasks: [] as Task[],
  taskRuns: [] as TaskRun[],
  health: { checkedAt: null, items: [] } as Health,
  backups: [] as Backup[],
  logs: [] as LogEntry[],
  queue: [] as Download[],
  history: [] as HistoryRecord[],
  media: {} as MediaSettings,
  mappings: [] as RemotePathMapping[],
  manualScan: { folder: '', downloadId: null, items: [] } as ManualImportScan,
  /** Every non-GET request the UI made, in order. */
  requests: [] as { method: string; path: string; body: unknown }[],
};

export function resetDb(): void {
  db.magazines = [
    makeMagazine(),
    makeMagazine({
      id: 2,
      title: 'Wired',
      sortTitle: 'wired',
      alternateTitles: [],
      tags: [],
      monitored: false,
      folder: 'Wired',
      statistics: stats(2, 2, 0, 1024),
    }),
  ];
  db.issues = [
    makeIssue({ id: 3, issueNumber: '2024-07', publishDate: '2024-07-01', sortIndex: 20240700 }),
    makeIssue({ id: 2, issueNumber: '2024-06', publishDate: '2024-06-01', sortIndex: 20240600, monitored: true, status: 'wanted' }),
    makeIssue({
      id: 1,
      status: 'downloaded',
      file: {
        id: 1,
        relativePath: 'NG - 2024-05.pdf',
        size: 52_428_800,
        format: 'pdf',
        quality: 'pdf',
        edition: null,
        dateAdded: '2026-10-15T09:00:00Z',
      },
    }),
  ];
  db.rootFolders = [{ id: 1, path: '/magazines', isDefault: true, accessible: true, freeSpace: 10 * 1024 ** 3 }];
  db.profiles = [
    {
      id: 1,
      name: 'Any',
      protocols: ['usenet', 'torrent'],
      mustContain: [],
      mustNotContain: [],
      items: [
        { quality: 'pdf_hires', allowed: true, maxSizeMb: null, upgradeUntil: true },
        { quality: 'pdf', allowed: true, maxSizeMb: null, upgradeUntil: false },
        { quality: 'epub', allowed: true, maxSizeMb: null, upgradeUntil: false },
      ],
    },
  ];
  db.naming = {
    magazineFolderPattern: '{magazine_title} ({first_issue_year})',
    yearFolderPattern: '',
    issueFilePattern: '{magazine_title} - {year}-{month} - Issue {issue_number}',
    replaceIllegalCharacters: true,
    colonReplacement: ' -',
  };
  db.indexers = [
    makeIndexer(),
    makeIndexer({
      id: 2,
      name: 'Torrents',
      implementation: 'torznab',
      protocol: 'torrent',
      consecutiveFailures: 3,
      disabledUntil: '2026-10-15T12:00:00Z',
      lastError: 'Timed out waiting for the indexer',
    }),
  ];
  db.prowlarr = { url: '', apiKey: '', lastSync: null };
  db.downloadClients = [
    {
      id: 1,
      name: 'SABnzbd',
      implementation: 'sabnzbd',
      protocol: 'usenet',
      enabled: true,
      priority: 1,
      settings: { host: 'sab.local', port: 8080, useSsl: false, urlBase: '', category: 'magazines', apiKey: '********', priority: 'default' },
    },
  ];
  db.downloadSettings = { redownloadFailed: true, maxRetries: 3 };
  db.notifications = [
    {
      id: 1, name: 'Discord', implementation: 'discord', enabled: true, events: ['grab', 'import', 'failure'],
      settings: { webhookUrl: '********', username: 'Magarr' }, templates: {}, lastSent: null, lastError: null,
    },
  ];
  db.tasks = [
    { name: 'downloads', label: 'Check downloads', intervalMinutes: 0.5, paused: false, running: false, lastRun: '2026-10-21T10:00:00Z', lastResult: '1 checked, 0 imported', lastOk: true, lastDurationMs: 0, nextRun: '2026-10-21T10:00:30Z' },
    { name: 'rss', label: 'RSS sync', intervalMinutes: 15, paused: false, running: false, lastRun: '2026-10-21T10:00:00Z', lastResult: '3 new release(s), 1 grabbed', lastOk: true, lastDurationMs: 820, nextRun: '2026-10-21T10:15:00Z' },
    { name: 'backlog', label: 'Backlog search', intervalMinutes: 60, paused: true, running: false, lastRun: null, lastResult: null, lastOk: true, lastDurationMs: 0, nextRun: null },
    { name: 'backup', label: 'Backup', intervalMinutes: 10080, paused: false, running: false, lastRun: '2026-10-20T10:00:00Z', lastResult: 'Failed: disk full', lastOk: false, lastDurationMs: 40, nextRun: '2026-10-27T10:00:00Z' },
  ];
  db.taskRuns = [
    { id: 2, startedAt: '2026-10-21T10:00:00Z', durationMs: 820, ok: true, result: '3 new release(s), 1 grabbed', manual: true },
    { id: 1, startedAt: '2026-10-21T09:45:00Z', durationMs: 400, ok: true, result: '0 new release(s), 0 grabbed', manual: false },
  ];
  db.health = {
    checkedAt: '2026-10-21T10:00:00Z',
    items: [
      { source: 'root_folder', level: 'error', message: 'Root folder /magazines is missing (not mounted?)' },
      { source: 'indexer', level: 'warning', message: 'Indexer NZBgeek is failing' },
      { source: 'automation', level: 'notice', message: 'Automatic searching is paused (Settings → Automation)' },
    ],
  };
  db.backups = [
    { name: 'magarr_backup_manual_2026.10.21_10.00.00.000.zip', kind: 'manual', size: 204_800, created: '2026-10-21T10:00:00Z' },
    { name: 'magarr_backup_scheduled_2026.10.14_10.00.00.000.zip', kind: 'scheduled', size: 198_000, created: '2026-10-14T10:00:00Z' },
  ];
  db.logs = [
    { id: 1, time: '2026-10-21T10:00:00Z', level: 'INFO', logger: 'magarr', message: 'Starting Magarr', data: { config_dir: '/config' } },
    { id: 2, time: '2026-10-21T10:00:01Z', level: 'WARNING', logger: 'magarr.indexers', message: 'Indexer search failed', data: {} },
  ];
  db.automation = {
    monitoringEnabled: true,
    rssIntervalMinutes: 15,
    backlogIntervalMinutes: 60,
    backlogBatchSize: 10,
    expectedLookaheadDays: 45,
    jobs: [
      { name: 'expected', lastRun: '2026-10-21T10:00:00Z', lastResult: '2 issue(s) added' },
      { name: 'rss', lastRun: '2026-10-21T10:05:00Z', lastResult: '12 new release(s), 1 grabbed' },
      { name: 'backlog', lastRun: null, lastResult: null },
    ],
  };
  db.queue = [
    makeDownload({ id: 10, status: 'downloading', progress: 0.5, title: 'National.Geographic.2024.07.True.PDF' }),
    makeDownload({
      id: 11,
      status: 'import_blocked',
      progress: 1,
      title: 'National.Geographic.2024.06.PDF',
      issueNumber: '2024-06',
      message: 'Could not tell which issue this file is',
    }),
  ];
  db.history = [
    { id: 2, eventType: 'imported', issueId: 1, magazineId: 1, magazineTitle: 'National Geographic', issueNumber: '2024-05', downloadId: 9, sourceTitle: 'NG.2024.05.PDF', data: { imported_path: '/magazines/NG/NG - 2024-05.pdf' }, date: '2026-10-21T10:00:00Z' },
    { id: 1, eventType: 'grabbed', issueId: 1, magazineId: 1, magazineTitle: 'National Geographic', issueNumber: '2024-05', downloadId: 9, sourceTitle: 'NG.2024.05.PDF', data: { client: 'SABnzbd' }, date: '2026-10-21T09:00:00Z' },
  ];
  db.media = { autoImport: true, usenetImportMode: 'move', torrentImportMode: 'hardlink', removeCompletedDownloads: true, recycleBin: '', fileChmod: '', folderChmod: '', chownUser: null, chownGroup: null };
  db.mappings = [{ id: 1, host: 'sab.local', remotePath: '/data', localPath: '/mnt/data' }];
  db.manualScan = {
    folder: '/inbox',
    downloadId: null,
    items: [
      { path: '/inbox/NG 2024-07.pdf', relativePath: 'NG 2024-07.pdf', size: 1000, format: 'pdf', quality: 'pdf', magazineId: 1, issueId: 3, issueNumber: '2024-07', warnings: [] },
      { path: '/inbox/random.pdf', relativePath: 'random.pdf', size: 500, format: 'pdf', quality: 'pdf', magazineId: null, issueId: null, issueNumber: null, warnings: ['Choose the magazine and issue'] },
    ],
  };
  db.search = {
    queries: ['National Geographic 2024'],
    indexers: [
      { indexerId: 1, name: 'Usenet', ok: true, releaseCount: 3, error: null, skippedUntil: null },
      {
        indexerId: 2,
        name: 'Torrents',
        ok: false,
        releaseCount: 0,
        error: 'Timed out waiting for the indexer',
        skippedUntil: null,
      },
    ],
    releases: [
      makeRelease({ title: 'National.Geographic.2024.07.True.PDF', ageDays: 3, size: 48_000_000 }),
      makeRelease({
        title: 'National Geographic July 2024 HQ',
        ageDays: 10,
        size: 90_000_000,
        protocol: 'torrent',
        indexer: 'Torrents',
        seeders: 42,
        leechers: 8,
        parsed: { ...makeRelease({ title: 'x' }).parsed, quality: 'pdf_hires' },
      }),
      makeRelease({
        title: 'National Geographic August 2024',
        ageDays: 1,
        size: 20_000_000,
        rejected: true,
        rejectionReasons: ['Wrong issue: release is 2024-08'],
        parsed: { ...makeRelease({ title: 'x' }).parsed, issueNumber: '2024-08' },
      }),
    ],
  };
  db.requests = [];
  live.__queueClients = [];
}

function withMagazine(issues: Issue[]): MagazineIssue[] {
  return issues.map((issue) => {
    const magazine = db.magazines.find((m) => m.id === issue.magazineId);
    return { ...issue, magazineTitle: magazine?.title ?? '?', magazineMonitored: magazine?.monitored ?? false };
  });
}

async function record(request: Request): Promise<unknown> {
  const text = await request.text();
  const body = text ? (JSON.parse(text) as unknown) : undefined;
  db.requests.push({ method: request.method, path: new URL(request.url).pathname, body });
  return body;
}

function makeRelease(overrides: Partial<Release> & { title: string }): Release {
  return {
    guid: overrides.title,
    indexerId: 1,
    indexer: 'Usenet',
    protocol: 'usenet',
    infoUrl: null,
    size: 48_000_000,
    publishDate: '2025-01-08T10:00:00Z',
    ageDays: 3,
    seeders: null,
    leechers: null,
    grabs: null,
    categories: [7010],
    parsed: {
      magazineTitle: 'National Geographic',
      issueNumber: '2024-07',
      year: 2024,
      month: 7,
      format: 'pdf',
      quality: 'pdf',
      edition: null,
      group: null,
      isPack: false,
      language: null,
    },
    rejected: false,
    rejectionReasons: [],
    ...overrides,
  };
}

const CLIENT_SCHEMA = [
  {
    implementation: 'sabnzbd',
    name: 'SABnzbd',
    protocol: 'usenet',
    fields: [
      { name: 'host', label: 'Host', type: 'string', required: true, default: null, description: null, options: null },
      { name: 'port', label: 'Port', type: 'number', required: false, default: 8080, description: null, options: null },
      { name: 'useSsl', label: 'Use SSL', type: 'boolean', required: false, default: false, description: null, options: null },
      { name: 'category', label: 'Category', type: 'string', required: false, default: 'magazines', description: null, options: null },
      { name: 'apiKey', label: 'API key', type: 'password', required: true, default: null, description: null, options: null },
      { name: 'priority', label: 'Priority', type: 'select', required: false, default: 'default', description: null, options: ['default', 'low', 'normal', 'high'] },
    ],
  },
  {
    implementation: 'qbittorrent',
    name: 'qBittorrent',
    protocol: 'torrent',
    fields: [
      { name: 'host', label: 'Host', type: 'string', required: true, default: null, description: null, options: null },
      { name: 'port', label: 'Port', type: 'number', required: false, default: 8080, description: null, options: null },
      { name: 'username', label: 'Username', type: 'string', required: false, default: 'admin', description: null, options: null },
      { name: 'password', label: 'Password', type: 'password', required: false, default: '', description: null, options: null },
    ],
  },
];

const notFound = (what: string) => HttpResponse.json({ message: `${what} not found` }, { status: 404 });

export const handlers = [
  queueSocket.addEventListener('connection', ({ client }) => {
    queueClients().push(client);
  }),
  http.get('/initialize.json', () =>
    HttpResponse.json({ appName: 'Magarr', version: '0.1.0', apiKey: TEST_API_KEY }),
  ),
  http.get('/api/v1/system/status', ({ request }) =>
    request.headers.get('X-Api-Key') === TEST_API_KEY
      ? HttpResponse.json(statusFixture)
      : HttpResponse.json({ message: 'Unauthorized' }, { status: 401 }),
  ),

  http.get('/api/v1/magazine', () => HttpResponse.json(db.magazines)),
  http.get('/api/v1/magazine/:id', ({ params }) => {
    const magazine = db.magazines.find((m) => m.id === Number(params.id));
    return magazine ? HttpResponse.json(magazine) : notFound('Magazine');
  }),
  http.post('/api/v1/magazine', async ({ request }) => {
    const body = (await record(request)) as Partial<Magazine>;
    const magazine = makeMagazine({ ...body, id: 99, statistics: stats() });
    db.magazines.push(magazine);
    return HttpResponse.json(magazine, { status: 201 });
  }),
  http.patch('/api/v1/magazine/:id', async ({ request, params }) => {
    const body = (await record(request)) as Partial<Magazine>;
    const magazine = db.magazines.find((m) => m.id === Number(params.id))!;
    Object.assign(magazine, body);
    return HttpResponse.json(magazine);
  }),
  http.delete('/api/v1/magazine/:id', async ({ request, params }) => {
    await record(request);
    db.magazines = db.magazines.filter((m) => m.id !== Number(params.id));
    return new HttpResponse(null, { status: 204 });
  }),
  http.post('/api/v1/magazine/:id/generate-issues', async ({ request }) => {
    await record(request);
    return HttpResponse.json({ created: [makeIssue({ id: 50 })], skipped: 0 });
  }),
  http.post('/api/v1/magazine/import', async ({ request }) => {
    await record(request);
    return HttpResponse.json({
      issuesCreated: 2,
      issuesUpdated: 0,
      issuesUnchanged: 1,
      magazinesCreated: [],
      errors: [{ row: 4, message: "Unknown magazine 'Byte'" }],
    });
  }),

  http.get('/api/v1/issue', ({ request }) => {
    const magazineId = Number(new URL(request.url).searchParams.get('magazineId'));
    return HttpResponse.json(db.issues.filter((i) => i.magazineId === magazineId));
  }),
  http.post('/api/v1/issue/bulk', async ({ request }) => {
    const body = (await record(request)) as { ids: number[]; monitored?: boolean; status?: string };
    const updated = db.issues.filter((i) => body.ids.includes(i.id));
    for (const issue of updated) {
      if (body.status === 'wanted' || body.monitored) Object.assign(issue, { monitored: true, status: 'wanted' });
    }
    return HttpResponse.json(updated);
  }),
  http.patch('/api/v1/issue/:id', async ({ request, params }) => {
    const body = (await record(request)) as Partial<Issue>;
    const issue = db.issues.find((i) => i.id === Number(params.id))!;
    Object.assign(issue, body);
    return HttpResponse.json(issue);
  }),
  http.post('/api/v1/issue/:id/search', async ({ request }) => {
    await record(request);
    return HttpResponse.json(db.search);
  }),

  http.get('/api/v1/indexer', () => HttpResponse.json(db.indexers)),
  http.get('/api/v1/indexer/categories', () =>
    HttpResponse.json([
      { id: 7000, name: 'Books' },
      { id: 7010, name: 'Books/Mags' },
    ]),
  ),
  http.post('/api/v1/indexer', async ({ request }) => {
    const body = (await record(request)) as Partial<Indexer>;
    const indexer = makeIndexer({ ...body, id: db.indexers.length + 1, apiKey: '********' });
    db.indexers.push(indexer);
    return HttpResponse.json(indexer, { status: 201 });
  }),
  http.post('/api/v1/indexer/test', async ({ request }) => {
    const body = (await record(request)) as { baseUrl: string };
    return HttpResponse.json(
      body.baseUrl.includes('bad')
        ? { ok: false, message: 'Indexer error 100: Incorrect user credentials', supportedCategories: [] }
        : { ok: true, message: 'Connection OK', supportedCategories: [{ id: 7020, name: 'EBook' }] },
    );
  }),
  http.post('/api/v1/indexer/sync-prowlarr', async ({ request }) => {
    await record(request);
    db.indexers.push(makeIndexer({ id: 9, name: 'NZBGeek (Prowlarr)', source: 'prowlarr', prowlarrId: 1 }));
    return HttpResponse.json({
      added: ['NZBGeek (Prowlarr)'],
      updated: [],
      removed: [],
      skipped: [{ name: 'Movies Only', reason: 'No book or magazine categories' }],
    });
  }),
  http.post('/api/v1/indexer/:id/test', async ({ request }) => {
    await record(request);
    return HttpResponse.json({ ok: true, message: 'Connection OK', supportedCategories: [] });
  }),
  http.patch('/api/v1/indexer/:id', async ({ request, params }) => {
    const body = (await record(request)) as Partial<Indexer>;
    const indexer = db.indexers.find((i) => i.id === Number(params.id))!;
    Object.assign(indexer, body);
    return HttpResponse.json(indexer);
  }),
  http.delete('/api/v1/indexer/:id', async ({ request, params }) => {
    await record(request);
    db.indexers = db.indexers.filter((i) => i.id !== Number(params.id));
    return new HttpResponse(null, { status: 204 });
  }),
  http.get('/api/v1/config/prowlarr', () => HttpResponse.json(db.prowlarr)),
  http.put('/api/v1/config/prowlarr', async ({ request }) => {
    const body = (await record(request)) as { url: string; apiKey: string };
    db.prowlarr = { url: body.url, apiKey: body.apiKey ? '********' : '', lastSync: null };
    return HttpResponse.json(db.prowlarr);
  }),
  http.post('/api/v1/config/prowlarr/test', async ({ request }) => {
    await record(request);
    return HttpResponse.json({ ok: true, message: 'Connected to Prowlarr 1.30.2', supportedCategories: [] });
  }),

  http.get('/api/v1/downloadclient/schema', () => HttpResponse.json(CLIENT_SCHEMA)),
  http.get('/api/v1/downloadclient', () => HttpResponse.json(db.downloadClients)),
  http.post('/api/v1/downloadclient', async ({ request }) => {
    const body = (await record(request)) as Omit<DownloadClient, 'id' | 'protocol'>;
    const client = {
      ...body,
      id: db.downloadClients.length + 1,
      protocol: body.implementation === 'sabnzbd' ? 'usenet' : 'torrent',
    } as DownloadClient;
    db.downloadClients.push(client);
    return HttpResponse.json(client, { status: 201 });
  }),
  http.post('/api/v1/downloadclient/test', async ({ request }) => {
    const body = (await record(request)) as { settings: Record<string, unknown> };
    if (body.settings.apiKey === 'bad') {
      return HttpResponse.json({ ok: false, message: 'SABnzbd: API Key Incorrect', warnings: [] });
    }
    return HttpResponse.json({
      ok: true,
      message: 'Connected to SABnzbd 5.1.3',
      warnings: body.settings.category === 'mags' ? ["Category 'mags' does not exist in SABnzbd"] : [],
    });
  }),
  http.post('/api/v1/downloadclient/:id/test', async ({ request }) => {
    await record(request);
    return HttpResponse.json({ ok: true, message: 'Connected to SABnzbd 5.1.3', warnings: [] });
  }),
  http.patch('/api/v1/downloadclient/:id', async ({ request, params }) => {
    const body = (await record(request)) as Partial<DownloadClient>;
    const client = db.downloadClients.find((c) => c.id === Number(params.id))!;
    Object.assign(client, body);
    return HttpResponse.json(client);
  }),
  http.delete('/api/v1/downloadclient/:id', async ({ request, params }) => {
    await record(request);
    db.downloadClients = db.downloadClients.filter((c) => c.id !== Number(params.id));
    return new HttpResponse(null, { status: 204 });
  }),
  http.get('/api/v1/config/downloads', () => HttpResponse.json(db.downloadSettings)),
  http.put('/api/v1/config/downloads', async ({ request }) => {
    db.downloadSettings = (await record(request)) as DownloadSettings;
    return HttpResponse.json(db.downloadSettings);
  }),
  http.get('/api/v1/config/automation', () => HttpResponse.json(db.automation)),
  http.put('/api/v1/config/automation', async ({ request }) => {
    db.automation = { ...db.automation, ...((await record(request)) as AutomationSettings) };
    return HttpResponse.json(db.automation);
  }),
  http.get('/api/v1/wanted', ({ request }) => {
    const params = new URL(request.url).searchParams;
    const page = Number(params.get('page') ?? 1);
    const pageSize = Number(params.get('pageSize') ?? 50);
    const magazineId = params.get('magazineId');
    const matching = withMagazine(
      db.issues.filter(
        (i) => i.status === (params.get('status') ?? 'wanted') && (!magazineId || i.magazineId === Number(magazineId)),
      ),
    ).sort((a, b) => (b.publishDate ?? '').localeCompare(a.publishDate ?? ''));
    return HttpResponse.json({
      total: matching.length,
      page,
      pageSize,
      records: matching.slice((page - 1) * pageSize, page * pageSize),
    });
  }),
  http.post('/api/v1/wanted/search', async ({ request }) => {
    const body = (await record(request)) as { issueIds: number[] };
    return HttpResponse.json({ queued: body.issueIds.length }, { status: 202 });
  }),
  http.get('/api/v1/calendar', ({ request }) => {
    const params = new URL(request.url).searchParams;
    const start = params.get('start')!;
    const end = params.get('end')!;
    const all = params.get('unmonitored') === 'true';
    return HttpResponse.json(
      withMagazine(db.issues.filter((i) => i.publishDate && i.publishDate >= start && i.publishDate <= end)).filter(
        (i) => all || i.magazineMonitored,
      ),
    );
  }),
  http.put('/api/v1/magazine/editor', async ({ request }) => {
    const { ids, ...changes } = (await record(request)) as { ids: number[] } & Partial<Magazine>;
    const updated = db.magazines.filter((m) => ids.includes(m.id)).map((m) => Object.assign(m, changes));
    return HttpResponse.json(updated);
  }),
  http.post('/api/v1/magazine/editor/delete', async ({ request }) => {
    const { ids } = (await record(request)) as { ids: number[] };
    db.magazines = db.magazines.filter((m) => !ids.includes(m.id));
    return new HttpResponse(null, { status: 204 });
  }),
  http.get('/api/v1/notification/schema', () =>
    HttpResponse.json({
      implementations: [
        { implementation: 'discord', name: 'Discord', fields: [
          { name: 'webhookUrl', label: 'Webhook URL', type: 'password', required: true, default: null, description: null, options: null },
          { name: 'username', label: 'Username', type: 'string', required: false, default: 'Magarr', description: null, options: null },
        ] },
        { implementation: 'ntfy', name: 'ntfy', fields: [
          { name: 'serverUrl', label: 'Server URL', type: 'string', required: false, default: 'https://ntfy.sh', description: null, options: null },
          { name: 'topic', label: 'Topic', type: 'string', required: true, default: null, description: null, options: null },
        ] },
      ],
      events: ['grab', 'import', 'upgrade', 'failure', 'health'],
      defaultTemplates: {
        grab: 'Grabbed {magazine} {issue}\n{release}', import: 'Imported {magazine} {issue}\n{path}',
        upgrade: 'Upgraded {magazine} {issue}\n{path}', failure: 'Failed: {magazine} {issue}\n{message}',
        health: 'Magarr health check\n{message}',
      },
      tokens: [{ name: 'magazine', description: 'Magazine title' }, { name: 'issue', description: 'Issue number' }],
    }),
  ),
  http.get('/api/v1/notification', () => HttpResponse.json(db.notifications)),
  http.post('/api/v1/notification/test', async ({ request }) => {
    await record(request);
    return HttpResponse.json({ ok: true, message: 'Test message sent to the service', warnings: [] });
  }),
  http.post('/api/v1/notification/preview', async ({ request }) => {
    const { template } = (await record(request)) as { template: string };
    const [title = '', ...body] = template.replace(/\{magazine\}/g, 'National Geographic').split('\n');
    return HttpResponse.json({ title, body: body.join('\n') });
  }),
  http.post('/api/v1/notification', async ({ request }) => {
    const body = (await record(request)) as Notification;
    const created = { ...body, id: db.notifications.length + 1, lastSent: null, lastError: null };
    db.notifications.push(created);
    return HttpResponse.json(created, { status: 201 });
  }),
  http.patch('/api/v1/notification/:id', async ({ request, params }) => {
    const body = (await record(request)) as Partial<Notification>;
    const row = db.notifications.find((n) => n.id === Number(params.id))!;
    Object.assign(row, body);
    return HttpResponse.json(row);
  }),
  http.delete('/api/v1/notification/:id', async ({ request, params }) => {
    await record(request);
    db.notifications = db.notifications.filter((n) => n.id !== Number(params.id));
    return new HttpResponse(null, { status: 204 });
  }),
  http.post('/api/v1/notification/:id/test', async ({ request }) => {
    await record(request);
    return HttpResponse.json({ ok: false, message: 'Discord returned HTTP 404: Unknown Webhook', warnings: [] });
  }),
  http.get('/api/v1/system/task', () => HttpResponse.json(db.tasks)),
  http.get('/api/v1/system/task/:name/history', () => HttpResponse.json(db.taskRuns)),
  http.post('/api/v1/system/task/:name/run', async ({ request, params }) => {
    await record(request);
    return HttpResponse.json({ message: `Started ${String(params.name)}` }, { status: 202 });
  }),
  http.get('/api/v1/system/health', ({ request }) => {
    const refresh = new URL(request.url).searchParams.get('refresh') === 'true';
    if (refresh) db.health = { checkedAt: '2026-10-21T11:00:00Z', items: [] };
    return HttpResponse.json(db.health);
  }),
  http.get('/api/v1/system/backup', () => HttpResponse.json(db.backups)),
  http.post('/api/v1/system/backup', async ({ request }) => {
    await record(request);
    const created: Backup = { name: 'magarr_backup_manual_2026.10.21_11.00.00.000.zip', kind: 'manual', size: 1024, created: '2026-10-21T11:00:00Z' };
    db.backups.unshift(created);
    return HttpResponse.json(created, { status: 201 });
  }),
  http.delete('/api/v1/system/backup/:name', async ({ request, params }) => {
    await record(request);
    db.backups = db.backups.filter((b) => b.name !== params.name);
    return new HttpResponse(null, { status: 204 });
  }),
  http.post('/api/v1/system/backup/upload', async ({ request }) => {
    db.requests.push({ method: 'POST', path: '/api/v1/system/backup/upload', body: request.headers.get('Content-Type') });
    return HttpResponse.json({ message: 'Restoring' });
  }),
  http.post('/api/v1/system/backup/:name/restore', async ({ request }) => {
    await record(request);
    return HttpResponse.json({ message: 'Restoring' });
  }),
  http.get('/api/v1/system/logs', ({ request }) => {
    const after = Number(new URL(request.url).searchParams.get('after') ?? 0);
    const entries = db.logs.filter((e) => e.id > after);
    return HttpResponse.json({ entries, lastId: db.logs.at(-1)?.id ?? after });
  }),
  http.post('/api/v1/release/grab', async ({ request }) => {
    const body = (await record(request)) as { guid: string; issueId: number };
    if (body.guid.includes('stale')) {
      return HttpResponse.json({ message: 'That release is no longer cached; search again' }, { status: 400 });
    }
    const issue = db.issues.find((i) => i.id === body.issueId)!;
    issue.download = { id: 77, status: 'queued', progress: 0, title: body.guid, message: null };
    return HttpResponse.json({ id: 77, status: 'queued', title: body.guid }, { status: 201 });
  }),

  http.get('/api/v1/queue', () => HttpResponse.json(db.queue)),
  http.post('/api/v1/queue/:id/import', async ({ request, params }) => {
    await record(request);
    const item = db.queue.find((d) => d.id === Number(params.id))!;
    db.queue = db.queue.filter((d) => d.id !== item.id);
    return HttpResponse.json({ ...item, status: 'imported', message: null });
  }),
  http.delete('/api/v1/queue/:id', async ({ request, params }) => {
    db.requests.push({ method: 'DELETE', path: new URL(request.url).pathname + new URL(request.url).search, body: undefined });
    db.queue = db.queue.filter((d) => d.id !== Number(params.id));
    return new HttpResponse(null, { status: 204 });
  }),
  http.get('/api/v1/history', ({ request }) => {
    const type = new URL(request.url).searchParams.get('eventType');
    const records = type ? db.history.filter((h) => h.eventType === type) : db.history;
    return HttpResponse.json({ total: records.length, page: 1, pageSize: 25, records });
  }),
  http.get('/api/v1/manualimport', ({ request }) => {
    const params = new URL(request.url).searchParams;
    return HttpResponse.json({ ...db.manualScan, folder: params.get('path') ?? '/downloads/x', downloadId: params.get('downloadId') ? Number(params.get('downloadId')) : null });
  }),
  http.post('/api/v1/manualimport', async ({ request }) => {
    const body = (await record(request)) as { files: { path: string; issueId: number }[] };
    return HttpResponse.json(
      body.files.map((f) => ({ path: f.path, issueId: f.issueId, importedTo: `/magazines/NG/${f.path.split('/').at(-1)}`, upgraded: false, error: null })),
    );
  }),
  http.get('/api/v1/config/mediamanagement', () => HttpResponse.json(db.media)),
  http.put('/api/v1/config/mediamanagement', async ({ request }) => {
    db.media = (await record(request)) as MediaSettings;
    return HttpResponse.json(db.media);
  }),
  http.get('/api/v1/remotepathmapping', () => HttpResponse.json(db.mappings)),
  http.post('/api/v1/remotepathmapping', async ({ request }) => {
    const body = (await record(request)) as Omit<RemotePathMapping, 'id'>;
    const mapping = { id: db.mappings.length + 1, ...body };
    db.mappings.push(mapping);
    return HttpResponse.json(mapping, { status: 201 });
  }),
  http.delete('/api/v1/remotepathmapping/:id', async ({ request, params }) => {
    await record(request);
    db.mappings = db.mappings.filter((m) => m.id !== Number(params.id));
    return new HttpResponse(null, { status: 204 });
  }),

  http.get('/api/v1/rootfolder', () => HttpResponse.json(db.rootFolders)),
  http.post('/api/v1/rootfolder', async ({ request }) => {
    const body = (await record(request)) as { path: string };
    if (!body.path.startsWith('/')) {
      return HttpResponse.json({ message: 'Root folder path must be absolute' }, { status: 400 });
    }
    const root = { id: db.rootFolders.length + 1, path: body.path, isDefault: false, accessible: true, freeSpace: 1 };
    db.rootFolders.push(root);
    return HttpResponse.json(root, { status: 201 });
  }),
  http.get('/api/v1/quality', () =>
    HttpResponse.json([
      { id: 'epub', name: 'EPUB', formats: ['epub'] },
      { id: 'pdf', name: 'PDF', formats: ['pdf'] },
      { id: 'pdf_hires', name: 'PDF (Hi-Res)', formats: ['pdf'] },
    ]),
  ),
  http.get('/api/v1/qualityprofile', () => HttpResponse.json(db.profiles)),
  http.post('/api/v1/qualityprofile', async ({ request }) => {
    const body = (await record(request)) as Omit<QualityProfile, 'id'>;
    const profile = { id: db.profiles.length + 1, ...body };
    db.profiles.push(profile);
    return HttpResponse.json(profile, { status: 201 });
  }),
  http.put('/api/v1/qualityprofile/:id', async ({ request, params }) => {
    const body = (await record(request)) as Omit<QualityProfile, 'id'>;
    const index = db.profiles.findIndex((p) => p.id === Number(params.id));
    db.profiles[index] = { id: Number(params.id), ...body };
    return HttpResponse.json(db.profiles[index]);
  }),
  http.get('/api/v1/config/naming', () => HttpResponse.json(db.naming)),
  http.put('/api/v1/config/naming', async ({ request }) => {
    db.naming = (await record(request)) as NamingConfig;
    return HttpResponse.json(db.naming);
  }),
  http.post('/api/v1/config/naming/preview', async ({ request }) => {
    const body = (await request.json()) as NamingConfig;
    if (!body.issueFilePattern.includes('{issue_number}')) {
      return HttpResponse.json({ message: 'Issue file pattern must include {issue_number}' }, { status: 400 });
    }
    return HttpResponse.json({
      magazineFolder: 'National Geographic (1888)',
      issuePath: `National Geographic (1888)/${body.yearFolderPattern ? '2014/' : ''}National Geographic - 2014-07 - Issue 045.pdf`,
      tokens: { magazineFolder: ['magazine_title'], yearFolder: ['year'], issueFile: ['issue_number', 'year'] },
    });
  }),
  http.get('/api/v1/library/unmapped', () => HttpResponse.json([])),
  http.post('/api/v1/library/scan', async ({ request }) => {
    await record(request);
    return HttpResponse.json([
      { rootFolderId: 1, path: '/magazines', filesFound: 3, filesAdded: 2, filesRemoved: 0, issuesCreated: 1, magazinesCreated: 1, unmapped: 1 },
    ]);
  }),
];
