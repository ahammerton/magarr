import { fireEvent, screen, waitFor } from '@testing-library/react';

import { setApiKey } from '../../api/client';
import { db, TEST_API_KEY } from '../../test/handlers';
import { renderWithProviders } from '../../test/render';
import { AutomationPage } from './AutomationPage';

beforeEach(() => setApiKey(TEST_API_KEY));

describe('AutomationPage', () => {
  it('shows when each job last ran', async () => {
    renderWithProviders(<AutomationPage />);
    const jobs = await screen.findAllByTestId('automation-job');
    expect(jobs.map((j) => j.textContent)).toEqual([
      expect.stringContaining('2 issue(s) added'),
      expect.stringContaining('12 new release(s), 1 grabbed'),
      expect.stringContaining('Not yet'),
    ]);
  });

  it('validates and saves the intervals', async () => {
    renderWithProviders(<AutomationPage />);
    const rss = await screen.findByLabelText('RSS sync interval');
    fireEvent.change(rss, { target: { value: '5' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Use 0 (off) or at least 10 minutes')).toBeInTheDocument();
    fireEvent.change(rss, { target: { value: '30' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(db.requests.at(-1)).toMatchObject({ method: 'PUT', path: '/api/v1/config/automation', body: { rssIntervalMinutes: 30 } }),
    );
    expect(db.requests.at(-1)!.body).not.toHaveProperty('jobs');
  });

  it('warns while automation is paused', async () => {
    renderWithProviders(<AutomationPage />);
    fireEvent.click(await screen.findByLabelText(/Automatic searching and grabbing/));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Automation is paused')).toBeInTheDocument();
    expect(db.automation.monitoringEnabled).toBe(false);
  });
});
