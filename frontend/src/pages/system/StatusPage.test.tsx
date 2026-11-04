import { screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';

import { setApiKey } from '../../api/client';
import { TEST_API_KEY } from '../../test/handlers';
import { renderWithProviders } from '../../test/render';
import { server } from '../../test/setup';
import { StatusPage } from './StatusPage';

describe('StatusPage', () => {
  beforeEach(() => setApiKey(TEST_API_KEY));

  it('renders the about table from the API', async () => {
    renderWithProviders(<StatusPage />);
    expect(await screen.findByText('0.1.0')).toBeInTheDocument();
    expect(screen.getByText('3.12.7')).toBeInTheDocument();
    expect(screen.getByText('Linux 6.8.0')).toBeInTheDocument();
    expect(screen.getByText('sqlite 3.46.1')).toBeInTheDocument();
    expect(screen.getByText('/config')).toBeInTheDocument();
    expect(screen.getByText('01:02:05')).toBeInTheDocument();
    expect(screen.getByText('API key')).toBeInTheDocument();
  });

  it('shows an error when the API fails', async () => {
    server.use(http.get('/api/v1/system/status', () => new HttpResponse(null, { status: 500 })));
    renderWithProviders(<StatusPage />);
    expect(await screen.findByText('Could not load system status.')).toBeInTheDocument();
  });
});
