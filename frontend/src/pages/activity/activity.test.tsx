import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';

import { setApiKey } from '../../api/client';
import { db, makeDownload, queueClients, TEST_API_KEY } from '../../test/handlers';
import { renderWithProviders } from '../../test/render';
import { HistoryPage } from './HistoryPage';
import { ManualImportPage } from './ManualImportPage';
import { QueuePage } from './QueuePage';

beforeEach(() => setApiKey(TEST_API_KEY));

describe('QueuePage', () => {
  it('lists downloads with status and messages', async () => {
    renderWithProviders(<QueuePage />);
    const rows = await screen.findAllByTestId('queue-row');
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByText('Downloading 50%')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('Needs attention')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('Could not tell which issue this file is')).toBeInTheDocument();
    // Only finished downloads can be imported.
    expect(within(rows[0]!).queryByLabelText(/Retry import/)).not.toBeInTheDocument();
    expect(within(rows[1]!).getByLabelText(/Import .* manually/)).toHaveAttribute('href', '/activity/import?downloadId=11');
  });

  it('updates live from the WebSocket', async () => {
    renderWithProviders(<QueuePage />);
    await screen.findAllByTestId('queue-row');
    expect(await screen.findByText('Live')).toBeInTheDocument();
    const [client] = queueClients();
    expect(client!.url.pathname).toBe('/api/v1/ws/queue');
    expect(client!.url.searchParams.get('apikey')).toBe(TEST_API_KEY);
    client!.send(JSON.stringify({ type: 'queue', queue: [makeDownload({ id: 12, status: 'downloading', progress: 0.9, title: 'Pushed' })] }));
    expect(await screen.findByText('Downloading 90%')).toBeInTheDocument();
    expect(screen.getAllByTestId('queue-row')).toHaveLength(1);
  });

  it('retries an import', async () => {
    renderWithProviders(<QueuePage />);
    fireEvent.click(await screen.findByLabelText('Retry import of National.Geographic.2024.06.PDF'));
    expect(await screen.findByText('Imported National.Geographic.2024.06.PDF')).toBeInTheDocument();
  });

  it('removes with options', async () => {
    renderWithProviders(<QueuePage />);
    fireEvent.click(await screen.findByLabelText('Remove National.Geographic.2024.07.True.PDF'));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByLabelText(/Blocklist this release/));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(db.requests.at(-1)?.path).toBe('/api/v1/queue/10?removeFromClient=true&blocklist=true'));
  });
});

describe('HistoryPage', () => {
  it('shows events and filters by type', async () => {
    renderWithProviders(<HistoryPage />);
    expect(await screen.findAllByTestId('history-row')).toHaveLength(2);
    expect(screen.getByText('/magazines/NG/NG - 2024-05.pdf')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('textbox', { name: 'Filter by event' }));
    fireEvent.click(await screen.findByRole('option', { name: 'Grabbed' }));
    await waitFor(() => expect(screen.getAllByTestId('history-row')).toHaveLength(1));
    expect(screen.getByText('SABnzbd')).toBeInTheDocument();
  });
});

describe('ManualImportPage', () => {
  function renderAt(route = '/activity/import') {
    return renderWithProviders(
      <Routes>
        <Route path="/activity/import" element={<ManualImportPage />} />
      </Routes>,
      { route },
    );
  }

  it('scans a folder, preselects confident matches and imports', async () => {
    renderAt();
    fireEvent.change(screen.getByLabelText(/^Folder or file/), { target: { value: '/inbox' } });
    fireEvent.click(screen.getByRole('button', { name: 'Scan' }));
    const rows = await screen.findAllByTestId('manual-row');
    expect(within(rows[0]!).getByLabelText('Import NG 2024-07.pdf')).toBeChecked();
    expect(within(rows[1]!).getByLabelText('Import random.pdf')).toBeDisabled(); // no issue chosen yet
    expect(within(rows[1]!).getByText('Choose the magazine and issue')).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Copy'));
    fireEvent.click(screen.getByRole('button', { name: 'Import 1 file(s)' }));
    await waitFor(() =>
      expect(db.requests.at(-1)?.body).toEqual({
        downloadId: null,
        mode: 'copy',
        files: [{ path: '/inbox/NG 2024-07.pdf', issueId: 3, quality: 'pdf' }],
      }),
    );
    expect(await screen.findByText('Imported to /magazines/NG/NG 2024-07.pdf')).toBeInTheDocument();
  });

  it('scans a download straight away when opened from the queue', async () => {
    renderAt('/activity/import?downloadId=11');
    expect(await screen.findAllByTestId('manual-row')).toHaveLength(2);
    expect(screen.queryByRole('button', { name: 'Scan' })).not.toBeInTheDocument();
    expect(screen.getByText('/downloads/x')).toBeInTheDocument();
  });
});
