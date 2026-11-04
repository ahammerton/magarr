import { fireEvent, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { Route, Routes } from 'react-router-dom';

import { setApiKey } from '../api/client';
import type { UnmappedFile } from '../api/types';
import { TEST_API_KEY } from '../test/handlers';
import { renderWithProviders } from '../test/render';
import { server } from '../test/setup';
import { AppLayout } from './AppLayout';

const unmapped = (id: number): UnmappedFile => ({
  id,
  rootFolderId: 1,
  rootFolderPath: '/magazines',
  relativePath: `Crash/Crash${id}.pdf`,
  size: 10,
  reason: 'Could not determine the issue from the file name',
  found: '2026-10-21T10:00:00Z',
});

function renderLayout() {
  return renderWithProviders(
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/library" element={<p>library</p>} />
      </Route>
    </Routes>,
    { route: '/library' },
  );
}

beforeEach(() => setApiKey(TEST_API_KEY));

describe('AppLayout', () => {
  it('shows how many files are unmapped next to Unmapped Files', async () => {
    server.use(http.get('/api/v1/library/unmapped', () => HttpResponse.json([1, 2, 3].map(unmapped))));
    renderLayout();
    const badge = await screen.findByLabelText('3 unmapped files');
    expect(badge).toHaveTextContent('3');
    expect(badge.closest('a')).toHaveAttribute('href', '/library/unmapped');
  });

  it('shows no count when nothing is unmapped', async () => {
    renderLayout();
    expect(await screen.findByText('Unmapped Files')).toBeInTheDocument();
    expect(screen.queryByLabelText(/unmapped files$/)).not.toBeInTheDocument();
  });

  it('shows health problems on System, red when one is an error', async () => {
    renderLayout();
    const badge = await screen.findByLabelText('2 health problems'); // the notice doesn't count
    expect(badge).toHaveTextContent('2');
    expect(badge.className).toMatch(/red|Badge/);
  });

  it('has keyboard shortcuts: ? for help, g then a letter to navigate', async () => {
    renderWithProviders(
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/library" element={<input aria-label="Search" data-shortcut-search />} />
          <Route path="/wanted" element={<p>wanted page</p>} />
        </Route>
      </Routes>,
      { route: '/library' },
    );
    fireEvent.keyDown(window, { key: '?' });
    const help = await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
    fireEvent.keyDown(help, { key: 'Escape' });

    fireEvent.keyDown(window, { key: '/' });
    expect(screen.getByLabelText('Search')).toHaveFocus();
    fireEvent.keyDown(screen.getByLabelText('Search'), { key: 'g' }); // typing: ignored
    fireEvent.keyDown(screen.getByLabelText('Search'), { key: 'w' });
    expect(screen.queryByText('wanted page')).not.toBeInTheDocument();

    screen.getByLabelText('Search').blur();
    fireEvent.keyDown(window, { key: 'g' });
    fireEvent.keyDown(window, { key: 'w' });
    expect(await screen.findByText('wanted page')).toBeInTheDocument();
  });

  it('cycles the theme', async () => {
    renderLayout();
    const toggle = await screen.findByLabelText(/^Dark theme/);
    fireEvent.click(toggle);
    expect(await screen.findByLabelText(/^Light theme/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/^Light theme/));
    expect(await screen.findByLabelText(/^Theme follows the system/)).toBeInTheDocument();
  });
});

