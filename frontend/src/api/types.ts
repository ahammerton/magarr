export type Frequency = 'weekly' | 'monthly' | 'quarterly' | 'ad-hoc';
export type IssueStatus = 'missing' | 'wanted' | 'downloaded' | 'ignored';

export interface MagazineStatistics {
  issueCount: number;
  downloadedCount: number;
  wantedCount: number;
  sizeOnDisk: number;
}

export interface Magazine {
  id: number;
  title: string;
  sortTitle: string;
  alternateTitles: string[];
  publisher: string | null;
  language: string;
  category: string | null;
  frequency: Frequency;
  firstIssueYear: number | null;
  tags: string[];
  qualityProfileId: number;
  rootFolderId: number;
  folder: string;
  path: string;
  monitored: boolean;
  posterUrl: string | null;
  /** Automatic searches skip issues published before this date (YYYY-MM-DD). */
  searchCutoff: string | null;
  /** RSS sync adds and grabs specials it sees, e.g. "Christmas Special 2026". */
  grabNewSpecials: boolean;
  /** Cover of the earliest downloaded issue, served by the API; shown when there's no poster URL. */
  coverUrl: string | null;
  issueNamingTemplate: string | null;
  notes: string | null;
  added: string;
  statistics: MagazineStatistics;
}

export type MagazineInput = Partial<
  Omit<Magazine, 'id' | 'sortTitle' | 'path' | 'coverUrl' | 'added' | 'statistics'>
>;

export interface IssueFile {
  id: number;
  relativePath: string;
  size: number;
  format: string;
  quality: string;
  edition: string | null;
  dateAdded: string;
}

export type DownloadStatus =
  | 'queued'
  | 'downloading'
  | 'paused'
  | 'warning'
  | 'pending_import'
  | 'import_blocked'
  | 'imported'
  | 'failed';

export interface IssueDownload {
  id: number;
  status: DownloadStatus;
  progress: number;
  title: string;
  message: string | null;
}

export interface Issue {
  id: number;
  magazineId: number;
  issueNumber: string;
  sortIndex: number;
  title: string | null;
  publishDate: string | null;
  coverUrl: string | null;
  monitored: boolean;
  status: IssueStatus;
  /** Last automatic (backlog or wanted-page) search. */
  lastSearchedAt: string | null;
  file: IssueFile | null;
  download: IssueDownload | null;
}

export interface IssueInput {
  issueNumber?: string;
  title?: string | null;
  publishDate?: string | null;
  coverUrl?: string | null;
  monitored?: boolean;
  status?: IssueStatus;
}

export interface RootFolder {
  id: number;
  path: string;
  isDefault: boolean;
  accessible: boolean;
  freeSpace: number | null;
}

export interface Quality {
  id: string;
  name: string;
  formats: string[];
}

export interface QualityProfileItem {
  quality: string;
  allowed: boolean;
  maxSizeMb: number | null;
  upgradeUntil: boolean;
}

export interface QualityProfile {
  id: number;
  name: string;
  items: QualityProfileItem[];
  protocols: Protocol[];
  mustContain: string[];
  mustNotContain: string[];
}

export interface NamingConfig {
  magazineFolderPattern: string;
  yearFolderPattern: string;
  issueFilePattern: string;
  replaceIllegalCharacters: boolean;
  colonReplacement: string;
}

export interface NamingPreview {
  magazineFolder: string;
  issuePath: string;
  tokens: { magazineFolder: string[]; yearFolder: string[]; issueFile: string[] };
}

export interface ScanResult {
  rootFolderId: number;
  path: string;
  filesFound: number;
  filesAdded: number;
  filesRemoved: number;
  issuesCreated: number;
  /** Unknown folders that became new (unmonitored) magazines. */
  magazinesCreated: number;
  unmapped: number;
}

export interface UnmappedFile {
  id: number;
  rootFolderId: number;
  rootFolderPath: string;
  relativePath: string;
  size: number;
  reason: string;
  found: string;
}

export interface CsvImportResult {
  issuesCreated: number;
  issuesUpdated: number;
  issuesUnchanged: number;
  magazinesCreated: string[];
  errors: { row: number; message: string }[];
}

export type Protocol = 'usenet' | 'torrent';
export type IndexerImplementation = 'newznab' | 'torznab';

export interface Category {
  id: number;
  name: string;
}

export interface Indexer {
  id: number;
  name: string;
  implementation: IndexerImplementation;
  protocol: Protocol;
  baseUrl: string;
  apiPath: string;
  apiKey: string;
  categories: number[];
  priority: number;
  enabled: boolean;
  tags: string[];
  requestInterval: number;
  source: 'manual' | 'prowlarr';
  prowlarrId: number | null;
  supportedCategories: Category[];
  consecutiveFailures: number;
  disabledUntil: string | null;
  lastError: string | null;
  lastSuccess: string | null;
}

export interface IndexerInput {
  name: string;
  implementation: IndexerImplementation;
  baseUrl: string;
  apiPath: string;
  apiKey: string;
  categories: number[];
  priority: number;
  enabled: boolean;
  tags: string[];
  requestInterval: number;
}

export interface TestResult {
  ok: boolean;
  message: string;
  supportedCategories: Category[];
}

export interface ProwlarrConfig {
  url: string;
  apiKey: string;
  lastSync: string | null;
}

export interface SyncResult {
  added: string[];
  updated: string[];
  removed: string[];
  skipped: { name: string; reason: string }[];
}

export interface Release {
  guid: string;
  title: string;
  indexerId: number | null;
  indexer: string;
  protocol: Protocol;
  infoUrl: string | null;
  size: number;
  publishDate: string | null;
  ageDays: number | null;
  seeders: number | null;
  leechers: number | null;
  grabs: number | null;
  categories: number[];
  parsed: {
    magazineTitle: string;
    issueNumber: string | null;
    year: number | null;
    month: number | null;
    format: string | null;
    quality: string;
    edition: string | null;
    group: string | null;
    isPack: boolean;
    language: string | null;
  };
  rejected: boolean;
  rejectionReasons: string[];
}

export interface IndexerOutcome {
  indexerId: number;
  name: string;
  ok: boolean;
  releaseCount: number;
  error: string | null;
  skippedUntil: string | null;
}

export interface SearchResult {
  queries: string[];
  indexers: IndexerOutcome[];
  releases: Release[];
}

export type DownloadClientImplementation = 'sabnzbd' | 'nzbget' | 'qbittorrent' | 'deluge' | 'transmission' | 'rtorrent';

export interface FieldSchema {
  name: string;
  label: string;
  type: 'string' | 'number' | 'boolean' | 'password' | 'select' | 'textarea';
  required: boolean;
  default: string | number | boolean | null;
  description: string | null;
  options: string[] | null;
}

export interface ImplementationSchema {
  implementation: DownloadClientImplementation;
  name: string;
  protocol: Protocol;
  fields: FieldSchema[];
}

export type ClientSettingsValues = Record<string, string | number | boolean>;

export interface DownloadClient {
  id: number;
  name: string;
  implementation: DownloadClientImplementation;
  protocol: Protocol;
  enabled: boolean;
  priority: number;
  settings: ClientSettingsValues;
}

export interface DownloadClientInput {
  name: string;
  implementation: DownloadClientImplementation;
  enabled: boolean;
  priority: number;
  settings: ClientSettingsValues;
}

export interface ClientTestResult {
  ok: boolean;
  message: string;
  warnings: string[];
}

export interface DownloadSettings {
  redownloadFailed: boolean;
  /** Automatic retries per issue before giving up. */
  maxRetries: number;
}

export type AutomationJobName = 'expected' | 'rss' | 'backlog';

export interface AutomationJob {
  name: AutomationJobName;
  lastRun: string | null;
  lastResult: string | null;
}

export interface AutomationSettings {
  monitoringEnabled: boolean;
  rssIntervalMinutes: number;
  backlogIntervalMinutes: number;
  backlogBatchSize: number;
  expectedLookaheadDays: number;
}

export interface Automation extends AutomationSettings {
  jobs: AutomationJob[];
}

/** An issue with its magazine's title, as listed on the Wanted and Calendar pages. */
export interface MagazineIssue extends Issue {
  magazineTitle: string;
  magazineMonitored: boolean;
}

export interface WantedPage {
  total: number;
  page: number;
  pageSize: number;
  records: MagazineIssue[];
}

export interface Download {
  id: number;
  issueId: number | null;
  magazineId: number | null;
  magazineTitle: string | null;
  issueNumber: string | null;
  downloadClientId: number | null;
  title: string;
  protocol: Protocol;
  status: DownloadStatus;
  progress: number;
  size: number;
  sizeLeft: number;
  outputPath: string | null;
  message: string | null;
  added: string;
  completedAt: string | null;
}

export type HistoryEventType =
  | 'grabbed'
  | 'download_completed'
  | 'download_failed'
  | 'imported'
  | 'upgraded'
  | 'import_failed'
  | 'file_deleted';

export interface HistoryRecord {
  id: number;
  eventType: HistoryEventType;
  issueId: number | null;
  magazineId: number | null;
  magazineTitle: string | null;
  issueNumber: string | null;
  downloadId: number | null;
  sourceTitle: string;
  data: Record<string, unknown>;
  date: string;
}

export interface HistoryPage {
  total: number;
  page: number;
  pageSize: number;
  records: HistoryRecord[];
}

export type ImportMode = 'move' | 'copy' | 'hardlink';

export interface MediaSettings {
  autoImport: boolean;
  usenetImportMode: ImportMode;
  torrentImportMode: ImportMode;
  removeCompletedDownloads: boolean;
  recycleBin: string;
  fileChmod: string;
  folderChmod: string;
  chownUser: number | null;
  chownGroup: number | null;
}

export interface RemotePathMapping {
  id: number;
  host: string;
  remotePath: string;
  localPath: string;
}

export interface ManualImportItem {
  path: string;
  relativePath: string;
  size: number;
  format: string | null;
  quality: string;
  magazineId: number | null;
  issueId: number | null;
  issueNumber: string | null;
  warnings: string[];
}

export interface ManualImportScan {
  folder: string;
  downloadId: number | null;
  items: ManualImportItem[];
}

export interface ManualImportOutcome {
  path: string;
  issueId: number | null;
  importedTo: string | null;
  upgraded: boolean;
  error: string | null;
}

export type NotificationImplementation = 'discord' | 'slack' | 'webhook' | 'ntfy' | 'pushover';
export type NotificationEvent = 'grab' | 'import' | 'upgrade' | 'failure' | 'health';

export interface NotificationSchema {
  implementations: { implementation: NotificationImplementation; name: string; fields: FieldSchema[] }[];
  events: NotificationEvent[];
  defaultTemplates: Record<NotificationEvent, string>;
  tokens: { name: string; description: string }[];
}

export interface Notification {
  id: number;
  name: string;
  implementation: NotificationImplementation;
  enabled: boolean;
  events: NotificationEvent[];
  /** Secrets come back masked. */
  settings: ClientSettingsValues;
  /** Overrides only; events without one use the default template. */
  templates: Partial<Record<NotificationEvent, string>>;
  lastSent: string | null;
  lastError: string | null;
}

export interface Task {
  name: string;
  label: string;
  intervalMinutes: number;
  paused: boolean;
  running: boolean;
  lastRun: string | null;
  lastResult: string | null;
  lastOk: boolean;
  lastDurationMs: number;
  nextRun: string | null;
}

export interface TaskRun {
  id: number;
  startedAt: string;
  durationMs: number;
  ok: boolean;
  result: string;
  manual: boolean;
}

export type HealthLevel = 'error' | 'warning' | 'notice';

export interface Health {
  checkedAt: string | null;
  items: { source: string; level: HealthLevel; message: string }[];
}

export interface Backup {
  name: string;
  kind: 'manual' | 'scheduled' | 'pre_restore';
  size: number;
  created: string;
}

export interface LogEntry {
  id: number;
  time: string;
  level: string;
  logger: string;
  message: string;
  data: Record<string, unknown>;
}

export interface LogPage {
  entries: LogEntry[];
  lastId: number;
}
