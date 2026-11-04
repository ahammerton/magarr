import { fireEvent, screen, waitFor, within } from '@testing-library/react';

import { setApiKey } from '../../api/client';
import { db, TEST_API_KEY } from '../../test/handlers';
import { renderWithProviders } from '../../test/render';
import { NotificationsPage } from './NotificationsPage';

beforeEach(() => setApiKey(TEST_API_KEY));

describe('NotificationsPage', () => {
  it('lists connections with their events and tests a saved one', async () => {
    renderWithProviders(<NotificationsPage />);
    const [row] = await screen.findAllByTestId('notification-row');
    expect(within(row!).getAllByText('Discord')).toHaveLength(2); // name and service
    expect(within(row!).getByText('Grab')).toBeInTheDocument();
    expect(within(row!).getByText('Failure')).toBeInTheDocument();
    fireEvent.click(within(row!).getByLabelText('Test Discord'));
    expect(await screen.findByText('Discord returned HTTP 404: Unknown Webhook')).toBeInTheDocument();
  });

  it('adds an ntfy connection with chosen events, a custom template and a test', async () => {
    renderWithProviders(<NotificationsPage />);
    const add = await screen.findByRole('button', { name: 'Add notification' });
    await waitFor(() => expect(add).toBeEnabled()); // once the list of services has loaded
    fireEvent.click(add);
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('textbox', { name: 'Service' }));
    fireEvent.click(await screen.findByRole('option', { name: 'ntfy' }));
    fireEvent.change(within(dialog).getByLabelText(/^Topic/), { target: { value: 'mags' } });
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Health problem' }));
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Upgrade' }));

    fireEvent.click(within(dialog).getByRole('button', { name: 'Message text' }));
    const grab = await within(dialog).findByRole('textbox', { name: /^Grab/ });
    fireEvent.change(grab, { target: { value: 'New {magazine}\nIssue {issue}' } });
    fireEvent.click(within(dialog).getAllByRole('button', { name: 'Preview' })[0]!);
    expect(await within(dialog).findByText('New National Geographic')).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole('button', { name: 'Send test' }));
    expect(await within(dialog).findByText('Test message sent to the service')).toBeInTheDocument();
    expect(db.requests.at(-1)).toMatchObject({ path: '/api/v1/notification/test', body: { implementation: 'ntfy', settings: { topic: 'mags' } } });

    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(db.requests.at(-1)).toMatchObject({
        method: 'POST',
        path: '/api/v1/notification',
        body: {
          name: 'ntfy',
          implementation: 'ntfy',
          events: ['grab', 'import', 'failure'],
          templates: { grab: 'New {magazine}\nIssue {issue}' },
        },
      }),
    );
  });

  it('deletes after confirming', async () => {
    renderWithProviders(<NotificationsPage />);
    fireEvent.click(await screen.findByLabelText('Delete Discord'));
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(db.notifications).toEqual([]));
  });
});
