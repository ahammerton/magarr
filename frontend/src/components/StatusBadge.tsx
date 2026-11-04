import { Badge } from '@mantine/core';

import { Tooltip } from '@mantine/core';

import type { IssueDownload, IssueStatus } from '../api/types';
import { t } from '../i18n';

const COLORS: Record<IssueStatus, string> = {
  downloaded: 'teal',
  wanted: 'orange',
  missing: 'gray',
  ignored: 'dark',
};

const DOWNLOAD_COLORS: Record<IssueDownload['status'], string> = {
  queued: 'blue',
  downloading: 'blue',
  paused: 'gray',
  warning: 'orange',
  pending_import: 'violet',
  import_blocked: 'orange',
  imported: 'teal',
  failed: 'red',
};

export function DownloadBadge({ download }: { download: Pick<IssueDownload, 'status' | 'progress' | 'title' | 'message'> }) {
  const label =
    download.status === 'downloading'
      ? t('download.status.downloadingPercent', { percent: Math.round(download.progress * 100) })
      : t(`download.status.${download.status}`);
  return (
    <Tooltip label={download.message ? `${download.title}: ${download.message}` : download.title} multiline w={320}>
      <Badge color={DOWNLOAD_COLORS[download.status]} variant="dot" style={{ minWidth: 'max-content' }}>
        {label}
      </Badge>
    </Tooltip>
  );
}

export function StatusBadge({ status }: { status: IssueStatus }) {
  return (
    <Badge color={COLORS[status]} variant={status === 'downloaded' ? 'filled' : 'light'}>
      {t(`status.issue.${status}`)}
    </Badge>
  );
}
