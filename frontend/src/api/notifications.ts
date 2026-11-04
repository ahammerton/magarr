import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiDelete, apiGet, apiPatch, apiPost } from './client';
import type {
  ClientSettingsValues,
  ClientTestResult,
  Notification,
  NotificationImplementation,
  NotificationSchema,
} from './types';

const keys = { list: ['notifications'] as const, schema: ['notifications', 'schema'] as const };

export function useNotificationSchema() {
  return useQuery({
    queryKey: keys.schema,
    queryFn: () => apiGet<NotificationSchema>('/api/v1/notification/schema'),
    staleTime: Infinity,
  });
}

export function useNotifications() {
  return useQuery({ queryKey: keys.list, queryFn: () => apiGet<Notification[]>('/api/v1/notification') });
}

export type NotificationInput = Omit<Notification, 'id' | 'lastSent' | 'lastError'> & { id?: number };

export function useSaveNotification() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: NotificationInput) =>
      id === undefined
        ? apiPost<Notification>('/api/v1/notification', body)
        : apiPatch<Notification>(`/api/v1/notification/${id}`, body),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.list }),
  });
}

export function useToggleNotification() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      apiPatch<Notification>(`/api/v1/notification/${id}`, { enabled }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.list }),
  });
}

export function useDeleteNotification() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiDelete(`/api/v1/notification/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.list }),
  });
}

export function useTestNotificationSettings() {
  return useMutation({
    mutationFn: (body: { implementation: NotificationImplementation; settings: ClientSettingsValues; id?: number }) =>
      apiPost<ClientTestResult>('/api/v1/notification/test', body),
  });
}

export function useTestSavedNotification() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiPost<ClientTestResult>(`/api/v1/notification/${id}/test`),
    onSettled: () => client.invalidateQueries({ queryKey: keys.list }),
  });
}

export function usePreviewTemplate() {
  return useMutation({
    mutationFn: (template: string) =>
      apiPost<{ title: string; body: string }>('/api/v1/notification/preview', { template }),
  });
}
