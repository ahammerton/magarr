import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';

import { setApiKey } from '../../api/client';
import { db, makeIssue, TEST_API_KEY } from '../../test/handlers';
import { renderWithProviders } from '../../test/render';
import { MagazineDetailPage } from './MagazineDetailPage';

beforeEach(() => setApiKey(TEST_API_KEY));

function renderDetail(id = 1) {
  return renderWithProviders(
    <Routes>
      <Route path="/magazine/:id" element={<MagazineDetailPage />} />
      <Route path="/library" element={<p>library page</p>} />
    </Routes>,
    { route: `/magazine/${id}` },
  );
}

describe('MagazineDetailPage', () => {
  it('shows magazine details and the issue table', async () => {
    renderDetail();
    expect(await screen.findByRole('heading', { name: 'National Geographic' })).toBeInTheDocument();
    expect(screen.getByText('Also known as Nat Geo')).toBeInTheDocument();
    expect(screen.getByText('/magazines/National Geographic (1888)')).toBeInTheDocument();
    const rows = await screen.findAllByTestId('issue-row');
    expect(rows).toHaveLength(3);
    expect(within(rows[0]!).getByText('Missing')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('Wanted')).toBeInTheDocument();
    expect(within(rows[2]!).getByText('PDF')).toBeInTheDocument();
    expect(within(rows[2]!).getByText('50.0 MB')).toBeInTheDocument();
  });

  it('filters issues by status', async () => {
    renderDetail();
    await screen.findAllByTestId('issue-row');
    fireEvent.click(screen.getByText('Wanted (1)'));
    expect(screen.getAllByTestId('issue-row')).toHaveLength(1);
  });

  it('marks selected issues wanted in bulk', async () => {
    renderDetail();
    await screen.findAllByTestId('issue-row');
    fireEvent.click(screen.getByLabelText('Select issue 2024-07'));
    fireEvent.click(screen.getByLabelText('Select issue 2024-06'));
    expect(screen.getByText('2 selected')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Mark wanted' }));

    await waitFor(() =>
      expect(db.requests.at(-1)).toEqual({
        method: 'POST',
        path: '/api/v1/issue/bulk',
        body: { ids: [3, 2], status: 'wanted' },
      }),
    );
    await waitFor(() => expect(screen.queryByText('2 selected')).not.toBeInTheDocument());
  });

  it('toggles monitoring on one issue', async () => {
    renderDetail();
    fireEvent.click(await screen.findByLabelText('Monitor issue 2024-07'));
    await waitFor(() =>
      expect(db.requests.at(-1)).toMatchObject({ method: 'PATCH', path: '/api/v1/issue/3', body: { monitored: true } }),
    );
    expect(await screen.findByLabelText('Unmonitor issue 2024-07')).toBeInTheDocument();
  });

  it('generates expected issues', async () => {
    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Generate issues' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('First issue date'), { target: { value: '2025-01-01' } });
    fireEvent.change(within(dialog).getByLabelText('Number of issues'), { target: { value: '24' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Generate' }));
    await waitFor(() =>
      expect(db.requests.at(-1)).toEqual({
        method: 'POST',
        path: '/api/v1/magazine/1/generate-issues',
        body: { start: '2025-01-01', count: 24, monitored: false, firstNumber: null },
      }),
    );
    expect(await screen.findByText('Created 1 issue(s), skipped 0 existing')).toBeInTheDocument();
  });

  it('generates numbered issues continuing the sequence, with dates', async () => {
    db.issues = [makeIssue({ id: 9, issueNumber: '359', publishDate: '2026-08-01', sortIndex: 359 })];
    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Generate issues' }));
    const dialog = await screen.findByRole('dialog');
    // The magazine already uses numbers, so numbering is preselected and continues at 360.
    expect(within(dialog).getByLabelText('First issue number')).toHaveValue('360');
    fireEvent.change(within(dialog).getByLabelText('Number of issues'), { target: { value: '3' } });
    expect(within(dialog).getByText('Creates issues 360 to 362. Existing numbers are skipped.')).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText('First issue date (optional)'), { target: { value: '2026-09-01' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Generate' }));
    await waitFor(() =>
      expect(db.requests.at(-1)).toEqual({
        method: 'POST',
        path: '/api/v1/magazine/1/generate-issues',
        body: { start: '2026-09-01', count: 3, monitored: false, firstNumber: 360 },
      }),
    );
  });

  it('numbers ad-hoc magazines without dates', async () => {
    db.magazines[0]!.frequency = 'ad-hoc';
    db.issues = [];
    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Generate issues' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/numbered without dates/)).toBeInTheDocument();
    expect(within(dialog).queryByLabelText(/First issue date/)).not.toBeInTheDocument();
    expect(within(dialog).getByLabelText('First issue number')).toHaveValue('1');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Generate' }));
    await waitFor(() =>
      expect(db.requests.at(-1)?.body).toEqual({ start: null, count: 12, monitored: false, firstNumber: 1 }),
    );
  });

  it('shows search results, indexer problems and rejection reasons', async () => {
    renderDetail();
    fireEvent.click(await screen.findByLabelText('Search for issue 2024-07'));
    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByText('Some indexers could not be searched')).toBeInTheDocument();
    expect(within(dialog).getByText(/Timed out waiting for the indexer/)).toBeInTheDocument();
    expect(within(dialog).getByText(/3 release\(s\), 2 matching this issue/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText('Wrong issue: release is 2024-08')).toBeInTheDocument();
    expect(within(dialog).getByText('PDF (Hi-Res)')).toBeInTheDocument();
  });

  it('grabs an approved release and shows the download on the issue', async () => {
    renderDetail();
    fireEvent.click(await screen.findByLabelText('Search for issue 2024-07'));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(await within(dialog).findByLabelText('Grab National.Geographic.2024.07.True.PDF'));
    expect(await within(dialog).findByText('Grabbed')).toBeInTheDocument();
    expect(db.requests.at(-1)).toEqual({
      method: 'POST',
      path: '/api/v1/release/grab',
      body: { guid: 'National.Geographic.2024.07.True.PDF', indexerId: 1, issueId: 3 },
    });
    fireEvent.keyDown(dialog, { key: 'Escape' });
    expect(await screen.findByText('Queued')).toBeInTheDocument();
  });

  it('asks before grabbing a rejected release', async () => {
    renderDetail();
    fireEvent.click(await screen.findByLabelText('Search for issue 2024-07'));
    const search = await screen.findByRole('dialog');
    fireEvent.click(await within(search).findByLabelText('Grab National Geographic August 2024'));
    const confirm = await screen.findByRole('dialog', { name: 'Grab a rejected release?' });
    expect(within(confirm).getByText(/Wrong issue: release is 2024-08/)).toBeInTheDocument();
    const before = db.requests.length;
    fireEvent.click(within(confirm).getByRole('button', { name: 'Grab anyway' }));
    await waitFor(() => expect(db.requests.length).toBe(before + 1));
    expect(db.requests.at(-1)?.body).toMatchObject({ guid: 'National Geographic August 2024' });
  });

  it('reports a stale release', async () => {
    db.search.releases[0]!.guid = 'stale-guid';
    renderDetail();
    fireEvent.click(await screen.findByLabelText('Search for issue 2024-07'));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(await within(dialog).findByLabelText('Grab National.Geographic.2024.07.True.PDF'));
    expect(await screen.findByText(/no longer cached/)).toBeInTheDocument();
  });

  it('shows download progress on issue rows', async () => {
    db.issues[0]!.download = { id: 5, status: 'downloading', progress: 0.42, title: 'x', message: null };
    db.issues[1]!.download = { id: 6, status: 'pending_import', progress: 1, title: 'y', message: null };
    renderDetail();
    expect(await screen.findByText('Downloading 42%')).toBeInTheDocument();
    expect(screen.getByText('Ready to import')).toBeInTheDocument();
  });

  it('sorts search results by column', async () => {
    renderDetail();
    fireEvent.click(await screen.findByLabelText('Search for issue 2024-07'));
    const dialog = await screen.findByRole('dialog');
    await within(dialog).findAllByTestId('release-row');
    const titles = () =>
      within(dialog)
        .getAllByTestId('release-row')
        .map((row) => row.querySelector('td:nth-child(2)')!.textContent);

    // Server order: approved first.
    expect(titles()).toEqual([
      'National.Geographic.2024.07.True.PDF',
      'National Geographic July 2024 HQ',
      'National Geographic August 2024',
    ]);
    fireEvent.click(within(dialog).getByRole('button', { name: /Size/ }));
    expect(titles()[0]).toBe('National Geographic July 2024 HQ'); // biggest first
    fireEvent.click(within(dialog).getByRole('button', { name: /Size/ }));
    expect(titles()[0]).toBe('National Geographic August 2024'); // then smallest
    fireEvent.click(within(dialog).getByRole('button', { name: /Age/ }));
    expect(titles()[0]).toBe('National Geographic August 2024'); // newest (1 day)
    expect(within(dialog).getByRole('columnheader', { name: /Age/ })).toHaveAttribute('aria-sort', 'ascending');
  });

  it('points to indexer settings when none apply', async () => {
    db.search = { queries: [], indexers: [], releases: [] };
    renderDetail();
    fireEvent.click(await screen.findByLabelText('Search for issue 2024-07'));
    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByText('No indexers')).toBeInTheDocument();
    expect(within(dialog).getByRole('link', { name: 'Indexers' })).toHaveAttribute('href', '/settings/indexers');
  });

  it('deletes the magazine after confirmation', async () => {
    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/Files on disk are not deleted/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete' }));
    expect(await screen.findByText('library page')).toBeInTheDocument();
    expect(db.magazines.map((m) => m.id)).toEqual([2]);
  });

  it('shows not found for an unknown magazine', async () => {
    renderDetail(404);
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
  });
});

describe('Magazine search cutoff', () => {
  it('is edited with the other settings', async () => {
    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('tab', { name: /Settings/ }));
    fireEvent.change(within(dialog).getByLabelText(/Only search issues published after/), { target: { value: '2010-01-01' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(db.requests.at(-1)).toMatchObject({ method: 'PATCH', path: '/api/v1/magazine/1', body: { searchCutoff: '2010-01-01' } }),
    );
  });
});

describe('Grab new specials', () => {
  it('is saved with the magazine settings', async () => {
    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('tab', { name: /Settings/ }));
    fireEvent.click(within(dialog).getByLabelText(/Grab new specials/));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(db.requests.at(-1)).toMatchObject({ method: 'PATCH', body: { grabNewSpecials: true } }),
    );
  });
});
