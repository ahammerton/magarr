import { fireEvent, screen, waitFor, within } from '@testing-library/react';

import { setApiKey } from '../../api/client';
import { db, TEST_API_KEY } from '../../test/handlers';
import { renderWithProviders } from '../../test/render';
import { MediaManagementPage } from './MediaManagementPage';
import { ProfilesPage } from './ProfilesPage';

beforeEach(() => setApiKey(TEST_API_KEY));

describe('MediaManagementPage', () => {
  it('lists and adds root folders', async () => {
    renderWithProviders(<MediaManagementPage />);
    expect(await screen.findByText('/magazines')).toBeInTheDocument();
    expect(screen.getByText('10.0 GB')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Add a root folder'), { target: { value: '/mnt/mags' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    expect(await screen.findByText('/mnt/mags')).toBeInTheDocument();
  });

  it('shows API errors when adding a bad path', async () => {
    renderWithProviders(<MediaManagementPage />);
    fireEvent.change(await screen.findByLabelText('Add a root folder'), { target: { value: 'relative' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    expect(await screen.findByText('Root folder path must be absolute')).toBeInTheDocument();
  });

  it('previews and saves naming', async () => {
    renderWithProviders(<MediaManagementPage />);
    expect(
      await screen.findByText(
        'National Geographic (1888)/National Geographic - 2014-07 - Issue 045.pdf',
      ),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/^Year folder/), { target: { value: '{year}' } });
    expect(
      await screen.findByText('National Geographic (1888)/2014/National Geographic - 2014-07 - Issue 045.pdf'),
    ).toBeInTheDocument();
    const card = screen.getByRole('heading', { name: 'Folder and file naming' }).closest('.mantine-Card-root') as HTMLElement;
    fireEvent.click(within(card).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(db.naming.yearFolderPattern).toBe(''));
  });

  it('shows invalid pattern errors in the preview', async () => {
    renderWithProviders(<MediaManagementPage />);
    fireEvent.change(await screen.findByLabelText('Issue file'), { target: { value: '{magazine_title}' } });
    expect(await screen.findByText('Issue file pattern must include {issue_number}')).toBeInTheDocument();
  });
});

describe('ProfilesPage', () => {
  it('lists profiles with allowed qualities', async () => {
    renderWithProviders(<ProfilesPage />);
    expect(await screen.findByText('Any')).toBeInTheDocument();
    expect(await screen.findByText('PDF (Hi-Res)')).toBeInTheDocument();
  });

  it('creates a profile with reordered qualities and a cutoff', async () => {
    renderWithProviders(<ProfilesPage />);
    await screen.findByText('Any');
    fireEvent.click(screen.getByRole('button', { name: 'Add profile' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText(/^Name/), { target: { value: 'Ebooks' } });
    fireEvent.click(within(dialog).getByLabelText('Move EPUB up'));
    fireEvent.click(within(dialog).getByLabelText('Allow PDF (Hi-Res)'));
    fireEvent.click(within(dialog).getByLabelText('Upgrade until EPUB'));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(db.profiles).toHaveLength(2));
    expect(db.profiles[1]).toMatchObject({
      name: 'Ebooks',
      items: [
        { quality: 'pdf_hires', allowed: false, upgradeUntil: false },
        { quality: 'epub', allowed: true, upgradeUntil: true },
        { quality: 'pdf', allowed: true, upgradeUntil: false },
      ],
    });
  });
});

describe('Importing settings', () => {
  it('saves import options', async () => {
    renderWithProviders(<MediaManagementPage />);
    fireEvent.change(await screen.findByLabelText(/^Recycle bin/), { target: { value: '/magazines/.recycle' } });
    fireEvent.change(screen.getByLabelText(/^File permissions/), { target: { value: '664' } });
    const card = screen.getByRole('heading', { name: 'Importing' }).closest('.mantine-Card-root') as HTMLElement;
    fireEvent.click(within(card).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(db.media).toMatchObject({ recycleBin: '/magazines/.recycle', fileChmod: '664', autoImport: true }));
  });
});
