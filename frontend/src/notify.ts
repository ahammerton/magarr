import { notifications } from '@mantine/notifications';

export function notifySuccess(message: string): void {
  notifications.show({ color: 'teal', message });
}

export function notifyError(error: unknown): void {
  const message = error instanceof Error ? error.message : String(error);
  notifications.show({ color: 'red', title: 'Error', message, autoClose: 8000 });
}
