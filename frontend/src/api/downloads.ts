import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from './client';
import type {
  ClientTestResult,
  Download,
  DownloadClient,
  DownloadClientInput,
  DownloadSettings,
  ImplementationSchema,
} from './types';

const keys = {
  clients: ['downloadClients'] as const,
  schema: ['downloadClientSchema'] as const,
  settings: ['downloadSettings'] as const,
};

export function useDownloadClientSchema() {
  return useQuery({
    queryKey: keys.schema,
    queryFn: () => apiGet<ImplementationSchema[]>('/api/v1/downloadclient/schema'),
    staleTime: Infinity,
  });
}

export function useDownloadClients() {
  return useQuery({ queryKey: keys.clients, queryFn: () => apiGet<DownloadClient[]>('/api/v1/downloadclient') });
}

export function useSaveDownloadClient() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...input }: DownloadClientInput & { id?: number }) =>
      id === undefined
        ? apiPost<DownloadClient>('/api/v1/downloadclient', input)
        : apiPatch<DownloadClient>(`/api/v1/downloadclient/${id}`, input),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.clients }),
  });
}

export function useToggleDownloadClient() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      apiPatch<DownloadClient>(`/api/v1/downloadclient/${id}`, { enabled }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.clients }),
  });
}

export function useDeleteDownloadClient() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiDelete(`/api/v1/downloadclient/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.clients }),
  });
}

/** Test unsaved settings; pass ``id`` when editing so masked secrets resolve to stored ones. */
export function useTestDownloadClientSettings() {
  return useMutation({
    mutationFn: (body: Pick<DownloadClientInput, 'implementation' | 'settings'> & { id?: number }) =>
      apiPost<ClientTestResult>('/api/v1/downloadclient/test', body),
  });
}

export function useTestSavedDownloadClient() {
  return useMutation({
    mutationFn: (id: number) => apiPost<ClientTestResult>(`/api/v1/downloadclient/${id}/test`),
  });
}

export function useDownloadSettings() {
  return useQuery({ queryKey: keys.settings, queryFn: () => apiGet<DownloadSettings>('/api/v1/config/downloads') });
}

export function useSaveDownloadSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: DownloadSettings) => apiPut<DownloadSettings>('/api/v1/config/downloads', body),
    onSuccess: (saved) => client.setQueryData(keys.settings, saved),
  });
}

export function useGrab() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { guid: string; indexerId: number | null; issueId: number }) =>
      apiPost<Download>('/api/v1/release/grab', body),
    // Only the issue list changes; re-running the search would cost indexer calls.
    onSuccess: () => client.invalidateQueries({ queryKey: ['issues'] }),
  });
}
