import { http, HttpResponse } from 'msw';

import { server } from '../test/setup';
import { ApiError, apiGet, initialize, setApiKey } from './client';

describe('api client', () => {
  it('initialize stores the API key and sends it on later requests', async () => {
    let seen: string | null = null;
    server.use(
      http.get('/api/v1/echo', ({ request }) => {
        seen = request.headers.get('X-Api-Key');
        return HttpResponse.json({ ok: true });
      }),
    );
    const init = await initialize();
    await apiGet('/api/v1/echo');
    expect(seen).toBe(init.apiKey);
  });

  it('throws ApiError with the status code on failure', async () => {
    setApiKey('wrong');
    await expect(apiGet('/api/v1/system/status')).rejects.toMatchObject({
      name: 'ApiError',
      status: 401,
    });
    await expect(apiGet('/api/v1/system/status')).rejects.toBeInstanceOf(ApiError);
  });
});
