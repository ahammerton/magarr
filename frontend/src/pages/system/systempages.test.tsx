import { fireEvent, screen, waitFor, within } from '@testing-library/react';

import { setApiKey } from '../../api/client';
import { db, TEST_API_KEY } from '../../test/handlers';
import { renderWithProviders } from '../../test/render';
import { BackupPage } from './BackupPage';
import { HealthPage } from './HealthPage';
import { LogsPage } from './LogsPage';
import { TasksPage } from './TasksPage';

beforeEach(() => setApiKey(TEST_API_KEY));

describe('HealthPage', () => {
  it('shows problems worst first and can check again', async () => {
    renderWithProviders(<HealthPage />);
    const items = await screen.findAllByTestId('health-item');
    expect(items.map((i) => i.textContent)).toEqual([
      'Root folder /magazines is missing (not mounted?)',
      'Indexer NZBgeek is failing',
      'Automatic searching is paused (Settings → Automation)',
    ]);
    expect(within(items[0]!).getByLabelText('Error')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Check now' }));
    expect(await screen.findByText('Everything is healthy')).toBeInTheDocument();
  });
});

describe('TasksPage', () => {
  it('lists tasks with schedules and results, runs one, and shows its history', async () => {
    renderWithProviders(<TasksPage />);
    const rows = await screen.findAllByTestId('task-row');
    expect(rows).toHaveLength(4);
    const [downloads, rss, backlog, backup] = rows;
    expect(within(downloads!).getByText('every 30 seconds')).toBeInTheDocument();
    expect(within(rss!).getByText('every 15 minutes')).toBeInTheDocument();
    expect(within(backlog!).getByText('Paused (Settings → Automation)')).toBeInTheDocument();
    expect(within(backup!).getByText('every 7 days')).toBeInTheDocument();
    expect(within(backup!).getByText('Failed')).toBeInTheDocument();

    fireEvent.click(within(rss!).getByLabelText('Run RSS sync now'));
    await waitFor(() => expect(db.requests.at(-1)).toMatchObject({ method: 'POST', path: '/api/v1/system/task/rss/run' }));
    expect(await screen.findByText('RSS sync started')).toBeInTheDocument();

    fireEvent.click(within(rss!).getByLabelText('Recent runs of RSS sync'));
    const runs = await screen.findAllByTestId('task-run');
    expect(runs).toHaveLength(2);
    expect(within(runs[0]!).getByText('Run now')).toBeInTheDocument();
  });
});

describe('BackupPage', () => {
  it('backs up now and restores after confirming', async () => {
    renderWithProviders(<BackupPage />);
    expect(await screen.findAllByTestId('backup-row')).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: 'Back up now' }));
    await waitFor(() => expect(screen.getAllByTestId('backup-row')).toHaveLength(3));

    fireEvent.click(screen.getByLabelText('Restore magarr_backup_scheduled_2026.10.14_10.00.00.000.zip'));
    fireEvent.click(await screen.findByRole('button', { name: 'Restore and restart' }));
    await waitFor(() =>
      expect(db.requests.at(-1)).toMatchObject({
        path: '/api/v1/system/backup/magarr_backup_scheduled_2026.10.14_10.00.00.000.zip/restore',
      }),
    );
    expect(await screen.findByText('Restarting Magarr')).toBeInTheDocument();
  });

  it('restores from an uploaded file', async () => {
    renderWithProviders(<BackupPage />);
    await screen.findAllByTestId('backup-row');
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File([new Uint8Array([80, 75])], 'old-backup.zip', { type: 'application/zip' });
    fireEvent.change(input, { target: { files: [file] } });
    expect(await screen.findByText(/Magarr will go back to old-backup.zip/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Restore and restart' }));
    await waitFor(() =>
      expect(db.requests.at(-1)).toMatchObject({ path: '/api/v1/system/backup/upload', body: 'application/zip' }),
    );
  });
});

describe('LogsPage', () => {
  it('tails the log', async () => {
    renderWithProviders(<LogsPage />);
    const rows = await screen.findAllByTestId('log-row');
    expect(rows.map((r) => within(r).getByText(/Starting Magarr|Indexer search failed/).textContent)).toEqual([
      'Starting Magarr',
      'Indexer search failed',
    ]);
    expect(within(rows[0]!).getByText('config_dir')).toBeInTheDocument();
  });
});
