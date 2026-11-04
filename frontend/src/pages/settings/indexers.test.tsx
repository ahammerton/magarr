import { fireEvent, screen, waitFor, within } from '@testing-library/react';

import { setApiKey } from '../../api/client';
import { db, TEST_API_KEY } from '../../test/handlers';
import { renderWithProviders } from '../../test/render';
import { IndexersPage } from './IndexersPage';

beforeEach(() => setApiKey(TEST_API_KEY));

describe('IndexersPage', () => {
  it('lists indexers with protocol and health', async () => {
    renderWithProviders(<IndexersPage />);
    const rows = await screen.findAllByTestId('indexer-row');
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByText('Usenet', { selector: 'span' })).toBeInTheDocument();
    expect(within(rows[0]!).getByText('OK')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('Torrent')).toBeInTheDocument();
    expect(within(rows[1]!).getByText(/Paused until/)).toBeInTheDocument();
  });

  it('adds an indexer after testing it', async () => {
    renderWithProviders(<IndexersPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Add indexer' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText(/^Name/), { target: { value: 'Geek' } });
    fireEvent.click(within(dialog).getByText('Torznab (BitTorrent)'));
    fireEvent.change(within(dialog).getByLabelText(/^URL/), { target: { value: 'https://geek.example' } });
    fireEvent.change(within(dialog).getByLabelText('API key'), { target: { value: 'abc' } });

    fireEvent.click(within(dialog).getByRole('button', { name: 'Test' }));
    expect(await within(dialog).findByText('Connection OK', { selector: '.mantine-Alert-title *' })).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(db.indexers).toHaveLength(3));
    expect(db.requests.at(-1)?.body).toMatchObject({
      name: 'Geek',
      implementation: 'torznab',
      baseUrl: 'https://geek.example',
      apiKey: 'abc',
      categories: [7010],
      priority: 25,
    });
  });

  it('shows test failures in the dialog', async () => {
    renderWithProviders(<IndexersPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Add indexer' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText(/^URL/), { target: { value: 'https://bad.example' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Test' }));
    expect(await within(dialog).findByText('Indexer error 100: Incorrect user credentials')).toBeInTheDocument();
  });

  it('validates required fields', async () => {
    renderWithProviders(<IndexersPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Add indexer' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    expect(await within(dialog).findByText('Name is required')).toBeInTheDocument();
    expect(within(dialog).getByText('Enter a URL starting with http:// or https://')).toBeInTheDocument();
  });

  it('edits with the masked key and toggles enabled', async () => {
    renderWithProviders(<IndexersPage />);
    fireEvent.click(await screen.findByLabelText('Edit Usenet'));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText(/^Priority/), { target: { value: '5' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(db.requests.at(-1)).toMatchObject({
        method: 'PATCH',
        path: '/api/v1/indexer/1',
        body: { priority: 5, apiKey: '********' },
      }),
    );

    fireEvent.click(screen.getByLabelText('Enable Torrents'));
    await waitFor(() =>
      expect(db.requests.at(-1)).toEqual({ method: 'PATCH', path: '/api/v1/indexer/2', body: { enabled: false } }),
    );
  });

  it('saves Prowlarr settings, tests and syncs', async () => {
    renderWithProviders(<IndexersPage />);
    fireEvent.change(await screen.findByLabelText('Prowlarr URL'), { target: { value: 'http://prowlarr:9696' } });
    fireEvent.change(screen.getByLabelText('API key', { selector: 'input:not([disabled])' }), {
      target: { value: 'PKEY' },
    });
    const sync = screen.getByRole('button', { name: 'Sync indexers' });
    expect(sync).toBeDisabled(); // unsaved changes

    fireEvent.click(screen.getAllByRole('button', { name: 'Test' })[0]!);
    expect(await screen.findByText('Connected to Prowlarr 1.30.2')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(db.prowlarr.url).toBe('http://prowlarr:9696'));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Sync indexers' })).toBeEnabled());

    fireEvent.click(screen.getByRole('button', { name: 'Sync indexers' }));
    expect(await screen.findByText('Added: NZBGeek (Prowlarr)')).toBeInTheDocument();
    expect(screen.getByText('Skipped Movies Only: No book or magazine categories')).toBeInTheDocument();
    expect(await screen.findByText('NZBGeek (Prowlarr)', { selector: 'p' })).toBeInTheDocument();
  });

  it('deletes an indexer after confirmation', async () => {
    renderWithProviders(<IndexersPage />);
    fireEvent.click(await screen.findByLabelText('Delete Torrents'));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(db.indexers.map((i) => i.name)).toEqual(['Usenet']));
  });
});
