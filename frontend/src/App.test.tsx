import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import { App } from './App';
import { Boot } from './Boot';
import { db } from './test/handlers';
import { renderWithProviders } from './test/render';
import { server } from './test/setup';

function renderApp(route: string) {
  return renderWithProviders(
    <Boot>
      <App />
    </Boot>,
    { route },
  );
}

describe('App shell', () => {
  it('renders the sidebar with every section', async () => {
    renderApp('/library');
    const nav = await screen.findByRole('navigation', { name: 'Main' });
    for (const label of ['Library', 'Calendar', 'Activity', 'Wanted', 'Settings', 'System']) {
      expect(within(nav).getByText(label)).toBeInTheDocument();
    }
    for (const label of ['Magazines', 'Add New', 'Import CSV', 'Unmapped Files']) {
      expect(within(nav).getByText(label)).toBeInTheDocument();
    }
  });

  it('redirects / to the magazine library', async () => {
    renderApp('/');
    expect(await screen.findByRole('heading', { name: 'Magazines' })).toBeInTheDocument();
    expect(await screen.findByText('National Geographic')).toBeInTheDocument();
  });

  it('shows an empty state with no magazines', async () => {
    db.magazines = [];
    renderApp('/library');
    expect(await screen.findByText('No magazines yet')).toBeInTheDocument();
  });

  it('redirects /settings to media management', async () => {
    renderApp('/settings');
    expect(await screen.findByRole('heading', { name: 'Media Management' })).toBeInTheDocument();
  });

  it('shows system status using the bootstrapped API key', async () => {
    renderApp('/system');
    expect(await screen.findByRole('heading', { name: 'Status' })).toBeInTheDocument();
    expect(await screen.findByText('0.1.0')).toBeInTheDocument();
  });

  it('shows a not-found page for unknown routes', async () => {
    renderApp('/does-not-exist');
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument();
  });

  it('shows a retry screen when the server is unreachable', async () => {
    server.use(http.get('/initialize.json', () => HttpResponse.error()));
    renderApp('/library');
    // Boot retries once (with backoff) before giving up.
    expect(
      await screen.findByText('Could not reach the Magarr server.', {}, { timeout: 4000 }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });
});

describe('navigation highlighting', () => {
  it.each([
    ['/library', 'Magazines'],
    ['/library/add', 'Add New'],
    ['/magazine/1', 'Magazines'],
    ['/settings/profiles', 'Profiles'],
  ])('on %s only %s is current', async (route, label) => {
    renderApp(route);
    const nav = await screen.findByRole('navigation', { name: 'Main' });
    await waitFor(() => {
      const current = within(nav)
        .queryAllByRole('link')
        .filter((link) => link.getAttribute('aria-current') === 'page');
      expect(current.map((link) => link.textContent)).toEqual([label]);
    });
  });
});

describe('sidebar sections with sub-pages', () => {
  it.each([
    ['/system/status', 'Library', 'Magazines'],
    ['/library', 'Settings', 'Media Management'],
    ['/library', 'System', 'Status'],
  ])('from %s, clicking %s opens its first page', async (start, section, heading) => {
    renderApp(start);
    const nav = await screen.findByRole('navigation', { name: 'Main' });
    fireEvent.click(within(nav).getByText(section));
    expect(await screen.findByRole('heading', { name: heading })).toBeInTheDocument();
  });
});
