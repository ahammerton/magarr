import { screen, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import { setApiKey } from '../api/client';
import { TEST_API_KEY } from '../test/handlers';
import { renderWithProviders } from '../test/render';
import { server } from '../test/setup';
import { Poster } from './Poster';

const COVER = '/api/v1/magazine/1/cover?v=1-100';

beforeEach(() => {
  setApiKey(TEST_API_KEY);
  // jsdom has no object URLs.
  URL.createObjectURL = vi.fn(() => 'blob:cover');
  URL.revokeObjectURL = vi.fn();
});

describe('Poster', () => {
  it('shows the first issue cover, fetched with the API key in a header', async () => {
    let key: string | null = null;
    server.use(
      http.get('/api/v1/magazine/1/cover', ({ request }) => {
        key = request.headers.get('X-Api-Key');
        return new HttpResponse(new Uint8Array([0xff, 0xd8]), { headers: { 'Content-Type': 'image/jpeg' } });
      }),
    );
    renderWithProviders(<Poster title="National Geographic" url={null} coverUrl={COVER} />);
    expect(await screen.findByRole('img', { name: 'National Geographic' })).toHaveAttribute('src', 'blob:cover');
    expect(key).toBe(TEST_API_KEY);
  });

  it('prefers a poster URL the user set', () => {
    renderWithProviders(<Poster title="Wired" url="https://img.example/wired.jpg" coverUrl={COVER} />);
    expect(screen.getByRole('img', { name: 'Wired' })).toHaveAttribute('src', 'https://img.example/wired.jpg');
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it('falls back to initials when there is no readable cover', async () => {
    server.use(http.get('/api/v1/magazine/1/cover', () => new HttpResponse(null, { status: 404 })));
    renderWithProviders(<Poster title="National Geographic" url={null} coverUrl={COVER} />);
    await waitFor(() => expect(URL.createObjectURL).not.toHaveBeenCalled());
    expect(screen.getByText('NG')).toBeInTheDocument();
  });
});
