import { fireEvent, screen, waitFor, within } from '@testing-library/react';

import { setApiKey } from '../../api/client';
import { db, makeIssue, TEST_API_KEY } from '../../test/handlers';
import { renderWithProviders } from '../../test/render';
import { WantedPage } from './WantedPage';

beforeEach(() => setApiKey(TEST_API_KEY));

describe('WantedPage', () => {
  it('lists wanted issues and searches the selected ones', async () => {
    db.issues.push(makeIssue({ id: 9, magazineId: 2, issueNumber: '2024-08', publishDate: '2024-08-01', monitored: true, status: 'wanted', lastSearchedAt: '2026-10-20T08:00:00Z' }));
    renderWithProviders(<WantedPage />);
    const rows = await screen.findAllByTestId('wanted-row');
    expect(rows.map((r) => within(r).getAllByRole('cell')[2]!.textContent)).toEqual(['2024-08', '2024-06']);
    expect(within(rows[0]!).getByText('Wired')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('(magazine unmonitored)')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('Never')).toBeInTheDocument();

    const search = screen.getByRole('button', { name: /Search selected/ });
    expect(search).toBeDisabled();
    fireEvent.click(screen.getByLabelText('Select issue National Geographic 2024-06'));
    fireEvent.click(screen.getByRole('button', { name: 'Search selected (1)' }));
    await waitFor(() =>
      expect(db.requests.at(-1)).toMatchObject({ method: 'POST', path: '/api/v1/wanted/search', body: { issueIds: [2] } }),
    );
    expect(await screen.findByText(/Searching 1 issue\(s\) in the background/)).toBeInTheDocument();
  });

  it('shows unmonitored issues and can mark them wanted', async () => {
    renderWithProviders(<WantedPage />);
    await screen.findAllByTestId('wanted-row');
    fireEvent.click(screen.getByText('Unmonitored'));
    expect(await screen.findByText('2024-07')).toBeInTheDocument();
    expect(screen.getAllByTestId('wanted-row')).toHaveLength(1);
    expect(screen.getByRole('button', { name: /Search selected/ })).toBeDisabled();
    fireEvent.click(screen.getByLabelText('Select all issues'));
    fireEvent.click(screen.getByRole('button', { name: 'Mark wanted' }));
    await waitFor(() =>
      expect(db.requests.at(-1)).toMatchObject({ path: '/api/v1/issue/bulk', body: { ids: [3], monitored: true } }),
    );
  });

  it('says when nothing is wanted', async () => {
    db.issues = db.issues.filter((i) => i.status !== 'wanted');
    renderWithProviders(<WantedPage />);
    expect(await screen.findByText(/Nothing is wanted/)).toBeInTheDocument();
  });
});
