import { fireEvent, screen, waitFor, within } from '@testing-library/react';

import { setApiKey } from '../../api/client';
import { db, makeIssue, TEST_API_KEY } from '../../test/handlers';
import { renderWithProviders } from '../../test/render';
import { CalendarPage } from './CalendarPage';

beforeEach(() => {
  setApiKey(TEST_API_KEY);
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date(2024, 5, 12)); // 12 June 2024
});
afterEach(() => vi.useRealTimers());

describe('CalendarPage', () => {
  it('shows the month with issues on their publish dates', async () => {
    renderWithProviders(<CalendarPage />);
    expect(await screen.findByRole('heading', { name: /June 2024/ })).toBeInTheDocument();
    // Monday-first grid: June 2024 starts on a Saturday, so the grid opens on Monday 27 May.
    const june1 = await screen.findByTestId('calendar-day-2024-06-01');
    await waitFor(() => expect(within(june1).getByText('National Geographic · 2024-06')).toBeInTheDocument());
    expect(screen.getByTestId('calendar-day-2024-05-27')).toBeInTheDocument();
    // ...and ends on Sunday 30 June: July isn't shown.
    expect(screen.getByTestId('calendar-day-2024-06-30')).toBeInTheDocument();
    expect(screen.queryByTestId('calendar-day-2024-07-01')).not.toBeInTheDocument();
    expect(within(june1).getByText('National Geographic · 2024-06').closest('a')).toHaveAttribute('href', '/magazine/1');
  });

  it('moves between months and can include unmonitored magazines', async () => {
    db.issues.push(makeIssue({ id: 9, magazineId: 2, issueNumber: '2024-05', publishDate: '2024-05-15' }));
    renderWithProviders(<CalendarPage />);
    await screen.findByRole('heading', { name: /June 2024/ });
    fireEvent.click(screen.getByLabelText('Previous month'));
    expect(await screen.findByRole('heading', { name: /May 2024/ })).toBeInTheDocument();
    const may15 = await screen.findByTestId('calendar-day-2024-05-15');
    expect(within(may15).queryByText('Wired · 2024-05')).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Show unmonitored magazines'));
    await waitFor(() => expect(within(may15).getByText('Wired · 2024-05')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Today' }));
    expect(await screen.findByRole('heading', { name: /June 2024/ })).toBeInTheDocument();
  });
});
