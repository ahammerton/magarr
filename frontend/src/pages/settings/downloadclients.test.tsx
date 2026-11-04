import { fireEvent, screen, waitFor, within } from '@testing-library/react';

import { setApiKey } from '../../api/client';
import { db, TEST_API_KEY } from '../../test/handlers';
import { renderWithProviders } from '../../test/render';
import { DownloadClientsPage } from './DownloadClientsPage';
import { ProfilesPage } from './ProfilesPage';

beforeEach(() => setApiKey(TEST_API_KEY));

describe('DownloadClientsPage', () => {
  it('lists clients with type, protocol and category', async () => {
    renderWithProviders(<DownloadClientsPage />);
    const [row] = await screen.findAllByTestId('client-row');
    expect(within(row!).getByText('SABnzbd', { selector: 'td' })).toBeInTheDocument();
    expect(within(row!).getByText('Usenet')).toBeInTheDocument();
    expect(within(row!).getByText('magazines')).toBeInTheDocument();
  });

  it('adds a client using fields from the schema, after testing', async () => {
    renderWithProviders(<DownloadClientsPage />);
    const add = await screen.findByRole('button', { name: 'Add download client' });
    await waitFor(() => expect(add).toBeEnabled()); // enabled once the schema loads
    fireEvent.click(add);
    const dialog = await screen.findByRole('dialog');
    // Defaults from the schema are filled in.
    expect(within(dialog).getByDisplayValue('8080')).toBeInTheDocument();
    expect(within(dialog).getByDisplayValue('magazines')).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText(/^Host/), { target: { value: '192.168.1.20' } });
    fireEvent.change(within(dialog).getByLabelText(/^Port/), { target: { value: '7777' } });
    fireEvent.change(within(dialog).getByLabelText(/^Category/), { target: { value: 'mags' } });
    fireEvent.change(within(dialog).getByLabelText(/^API key/), { target: { value: 'k' } });

    fireEvent.click(within(dialog).getByRole('button', { name: 'Test' }));
    expect(await within(dialog).findByText("Category 'mags' does not exist in SABnzbd")).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(db.downloadClients).toHaveLength(2));
    expect(db.downloadClients[1]).toMatchObject({
      name: 'SABnzbd',
      implementation: 'sabnzbd',
      priority: 1,
      enabled: true,
      settings: { host: '192.168.1.20', port: 7777, useSsl: false, category: 'mags', apiKey: 'k', priority: 'default' },
    });
  });

  it('switching type swaps the fields', async () => {
    renderWithProviders(<DownloadClientsPage />);
    const add = await screen.findByRole('button', { name: 'Add download client' });
    await waitFor(() => expect(add).toBeEnabled()); // enabled once the schema loads
    fireEvent.click(add);
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('textbox', { name: 'Type' }));
    fireEvent.click(await screen.findByRole('option', { name: /qBittorrent/ }));
    expect(await within(dialog).findByLabelText(/^Username/)).toHaveValue('admin');
    expect(within(dialog).queryByLabelText(/^API key/)).not.toBeInTheDocument();
    expect(within(dialog).getByLabelText(/^Name/)).toHaveValue('qBittorrent');
  });

  it('edits with the masked secret and shows test failures', async () => {
    renderWithProviders(<DownloadClientsPage />);
    fireEvent.click(await screen.findByLabelText('Edit SABnzbd'));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByLabelText(/^API key/)).toHaveValue('********');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Test' }));
    await waitFor(() => expect(db.requests.at(-1)?.body).toMatchObject({ id: 1, settings: { apiKey: '********' } }));
    fireEvent.change(within(dialog).getByLabelText(/^API key/), { target: { value: 'bad' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Test' }));
    expect(await within(dialog).findByText('SABnzbd: API Key Incorrect')).toBeInTheDocument();
  });

  it('toggles failed-download handling', async () => {
    renderWithProviders(<DownloadClientsPage />);
    fireEvent.click(await screen.findByLabelText(/Redownload failed releases/));
    await waitFor(() => expect(db.downloadSettings).toEqual({ redownloadFailed: false, maxRetries: 3 }));
  });

  it('saves the retry limit when the field loses focus', async () => {
    renderWithProviders(<DownloadClientsPage />);
    const retries = await screen.findByLabelText(/Automatic retries per issue/);
    fireEvent.change(retries, { target: { value: '1' } });
    fireEvent.blur(retries);
    await waitFor(() => expect(db.downloadSettings).toEqual({ redownloadFailed: true, maxRetries: 1 }));
  });
});

describe('ProfilesPage decision rules', () => {
  it('saves protocols and must/must-not terms', async () => {
    renderWithProviders(<ProfilesPage />);
    fireEvent.click(await screen.findByLabelText('Edit Any'));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByLabelText('Torrent'));
    const must = within(dialog).getByLabelText(/^Must contain/);
    fireEvent.change(must, { target: { value: 'True PDF' } });
    fireEvent.keyDown(must, { key: 'Enter' });
    const mustNot = within(dialog).getByLabelText(/^Must not contain/);
    fireEvent.change(mustNot, { target: { value: '/spanish|italian/' } });
    fireEvent.keyDown(mustNot, { key: 'Enter' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(db.requests.at(-1)?.body).toMatchObject({
        protocols: ['usenet'],
        mustContain: ['True PDF'],
        mustNotContain: ['/spanish|italian/'],
      }),
    );
  });
});

describe('Remote path mappings', () => {
  it('lists, adds and removes mappings', async () => {
    renderWithProviders(<DownloadClientsPage />);
    expect(await screen.findAllByTestId('mapping-row')).toHaveLength(1);
    fireEvent.change(screen.getByRole('textbox', { name: 'Client host' }), { target: { value: '192.168.1.20' } });
    fireEvent.change(screen.getByLabelText("Client's path"), { target: { value: '/data/usenet/complete' } });
    fireEvent.change(screen.getByLabelText("Magarr's path"), { target: { value: '/downloads' } });
    const card = screen.getByRole('heading', { name: 'Remote path mappings' }).closest('.mantine-Card-root') as HTMLElement;
    fireEvent.click(within(card).getByRole('button', { name: 'Add' }));
    await waitFor(() => expect(screen.getAllByTestId('mapping-row')).toHaveLength(2));
    expect(db.mappings[1]).toMatchObject({ host: '192.168.1.20', remotePath: '/data/usenet/complete', localPath: '/downloads' });
    fireEvent.click(screen.getByLabelText('Remove mapping for /data'));
    await waitFor(() => expect(screen.getAllByTestId('mapping-row')).toHaveLength(1));
  });
});
