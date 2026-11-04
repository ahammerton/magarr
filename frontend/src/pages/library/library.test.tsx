import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';

import { setApiKey } from '../../api/client';
import { db, TEST_API_KEY } from '../../test/handlers';
import { renderWithProviders } from '../../test/render';
import { AddMagazinePage } from './AddMagazinePage';
import { ImportCsvPage } from './ImportCsvPage';
import { MagazineIndexPage } from './MagazineIndexPage';

beforeEach(() => {
  setApiKey(TEST_API_KEY);
  localStorage.clear();
});

describe('MagazineIndexPage', () => {
  it('shows a poster grid with progress', async () => {
    renderWithProviders(<MagazineIndexPage />);
    const cards = await screen.findAllByTestId('magazine-card');
    expect(cards).toHaveLength(2);
    expect(within(cards[0]!).getByText('1/3')).toBeInTheDocument();
    expect(within(cards[1]!).getByText('Unmonitored')).toBeInTheDocument();
    expect(cards[0]).toHaveAttribute('href', '/magazine/1');
  });

  it('switches to a table and remembers the choice', async () => {
    renderWithProviders(<MagazineIndexPage />);
    await screen.findAllByTestId('magazine-card');
    fireEvent.click(screen.getByLabelText('Table'));
    const table = await screen.findByRole('table');
    expect(within(table).getByRole('link', { name: 'Wired' })).toBeInTheDocument();
    expect(await within(table).findAllByText('Any')).toHaveLength(2);
    expect(localStorage.getItem('magarr.library.view')).toBe('table');
  });

  it('filters by title, alternate title and tag', async () => {
    renderWithProviders(<MagazineIndexPage />);
    await screen.findAllByTestId('magazine-card');
    const filter = screen.getByLabelText('Filter magazines');
    fireEvent.change(filter, { target: { value: 'nat geo' } });
    expect(screen.getAllByTestId('magazine-card')).toHaveLength(1);
    fireEvent.change(filter, { target: { value: 'zzz' } });
    expect(screen.getByText('No magazines match the filter.')).toBeInTheDocument();
  });

  it('runs a library scan', async () => {
    renderWithProviders(<MagazineIndexPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Scan library' }));
    expect(await screen.findByText('Scan finished: 1 new magazine(s), 2 file(s) added, 1 unmapped. New magazines are unmonitored.')).toBeInTheDocument();
  });
});

describe('AddMagazinePage', () => {
  function renderWizard() {
    return renderWithProviders(
      <Routes>
        <Route path="/library/add" element={<AddMagazinePage />} />
        <Route path="/magazine/:id" element={<p>detail page</p>} />
      </Routes>,
      { route: '/library/add' },
    );
  }

  it('requires a title before moving on', async () => {
    renderWizard();
    fireEvent.click(await screen.findByRole('button', { name: 'Next' }));
    expect(await screen.findByText('Title is required')).toBeInTheDocument();
  });

  it('walks through the steps and creates the magazine', async () => {
    renderWizard();
    fireEvent.change(await screen.findByLabelText(/^Title/), { target: { value: 'Byte' } });
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    // Defaults are preselected from the API.
    expect(await screen.findByDisplayValue('/magazines')).toBeInTheDocument();
    expect(await screen.findByDisplayValue('Any')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(await screen.findByText('Byte')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Add magazine' }));

    expect(await screen.findByText('detail page')).toBeInTheDocument();
    const post = db.requests.find((r) => r.method === 'POST' && r.path === '/api/v1/magazine');
    expect(post?.body).toMatchObject({
      title: 'Byte',
      frequency: 'monthly',
      rootFolderId: 1,
      qualityProfileId: 1,
      monitored: true,
      publisher: null,
    });
  });

  it('warns when there is no root folder', async () => {
    db.rootFolders = [];
    renderWizard();
    expect(await screen.findByText('No root folder')).toBeInTheDocument();
  });
});

describe('ImportCsvPage', () => {
  it('imports pasted CSV and shows the result', async () => {
    renderWithProviders(<ImportCsvPage />);
    fireEvent.change(screen.getByLabelText('CSV'), {
      target: { value: 'magazine,issue\nNational Geographic,1\n' },
    });
    fireEvent.click(screen.getByLabelText('Mark new issues as wanted'));
    fireEvent.click(screen.getByRole('button', { name: 'Import' }));

    expect(await screen.findByText('2 issue(s) created')).toBeInTheDocument();
    expect(screen.getByText("Unknown magazine 'Byte'")).toBeInTheDocument();
    await waitFor(() =>
      expect(db.requests.at(-1)?.body).toEqual({
        csv: 'magazine,issue\nNational Geographic,1\n',
        createMissing: false,
        monitored: true,
      }),
    );
  });
});

describe('MagazineIndexPage filters, sorting and bulk edits', () => {
  const titles = () => screen.getAllByTestId('magazine-card').map((c) => within(c).getByText(/National Geographic|Wired/).textContent);

  it('filters with presets and saved filters', async () => {
    renderWithProviders(<MagazineIndexPage />);
    await screen.findAllByTestId('magazine-card');
    fireEvent.click(screen.getByRole('button', { name: 'All' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: 'Unmonitored' }));
    await waitFor(() => expect(titles()).toEqual(['Wired']));

    fireEvent.click(screen.getByRole('button', { name: 'Unmonitored' }));
    fireEvent.click(await screen.findByRole('menuitem', { name: 'New filter…' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText(/^Filter name/), { target: { value: 'Science' } });
    fireEvent.change(within(dialog).getByLabelText('Tag contains'), { target: { value: 'sci' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(titles()).toEqual(['National Geographic']));
    expect(JSON.parse(localStorage.getItem('magarr.library.filters')!)[0]).toMatchObject({ name: 'Science', tag: 'sci' });
  });

  it('sorts, and lets posters be dragged into a custom order', async () => {
    renderWithProviders(<MagazineIndexPage />);
    await screen.findAllByTestId('magazine-card');
    expect(titles()).toEqual(['National Geographic', 'Wired']);
    fireEvent.click(screen.getByRole('textbox', { name: 'Sort' }));
    fireEvent.click(await screen.findByRole('option', { name: 'My order' }));
    expect(await screen.findByText(/Drag posters to arrange them/)).toBeInTheDocument();

    const [ng, wired] = screen.getAllByTestId('magazine-card');
    const dataTransfer = { effectAllowed: '', dropEffect: '' };
    fireEvent.dragStart(wired!, { dataTransfer });
    fireEvent.dragOver(ng!, { dataTransfer });
    fireEvent.drop(ng!, { dataTransfer });
    await waitFor(() => expect(titles()).toEqual(['Wired', 'National Geographic']));
    expect(JSON.parse(localStorage.getItem('magarr.library.order')!)).toEqual([2, 1]);
  });

  it('edits and deletes selected magazines from the table', async () => {
    localStorage.setItem('magarr.library.view', 'table');
    renderWithProviders(<MagazineIndexPage />);
    await screen.findAllByTestId('magazine-row');
    fireEvent.click(screen.getByLabelText('Select all magazines'));
    const toolbar = await screen.findByTestId('bulk-toolbar');
    expect(within(toolbar).getByText('2 selected')).toBeInTheDocument();
    fireEvent.click(within(toolbar).getByRole('button', { name: 'Unmonitor' }));
    await waitFor(() =>
      expect(db.requests.at(-1)).toMatchObject({ method: 'PUT', path: '/api/v1/magazine/editor', body: { ids: [1, 2], monitored: false } }),
    );

    fireEvent.click(screen.getByLabelText('Select Wired'));
    fireEvent.click(within(await screen.findByTestId('bulk-toolbar')).getByRole('button', { name: 'Delete' }));
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Delete' }));
    await waitFor(() =>
      expect(db.requests.at(-1)).toMatchObject({ method: 'POST', path: '/api/v1/magazine/editor/delete', body: { ids: [2] } }),
    );
  });
});

