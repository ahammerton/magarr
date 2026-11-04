import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { apiDelete, apiGet, apiPost, getApiKey } from './client';
import type {
  Download,
  HistoryEventType,
  HistoryPage,
  ManualImportOutcome,
  ManualImportScan,
} from './types';

const QUEUE_KEY = ['queue'] as const;

/** Queue kept live over a WebSocket; falls back to polling while the socket is down. */
export function useQueue() {
  const client = useQueryClient();
  const [live, setLive] = useState(false);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    let closed = false;

    const connect = () => {
      const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const url = `${scheme}://${window.location.host}/api/v1/ws/queue?apikey=${encodeURIComponent(getApiKey())}`;
      socket = new WebSocket(url);
      socket.onopen = () => {
        attempt = 0;
        setLive(true);
      };
      socket.onmessage = (event) => {
        const message = JSON.parse(String(event.data)) as { type: string; queue?: Download[] };
        if (message.type === 'queue' && message.queue) {
          client.setQueryData(QUEUE_KEY, message.queue);
          // Issue rows show download status too.
          void client.invalidateQueries({ queryKey: ['issues'] });
        }
      };
      socket.onclose = () => {
        setLive(false);
        if (closed) return;
        attempt += 1;
        retry = setTimeout(connect, Math.min(30_000, 1000 * 2 ** attempt));
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      socket?.close();
    };
  }, [client]);

  const query = useQuery({
    queryKey: QUEUE_KEY,
    queryFn: () => apiGet<Download[]>('/api/v1/queue'),
    refetchInterval: live ? false : 10_000,
  });
  return { ...query, live };
}

export function useRemoveFromQueue() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, removeFromClient, blocklist }: { id: number; removeFromClient: boolean; blocklist: boolean }) =>
      apiDelete(`/api/v1/queue/${id}?removeFromClient=${removeFromClient}&blocklist=${blocklist}`),
    onSuccess: () => client.invalidateQueries({ queryKey: QUEUE_KEY }),
  });
}

export function useRetryImport() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiPost<Download>(`/api/v1/queue/${id}/import`),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: QUEUE_KEY }),
        client.invalidateQueries({ queryKey: ['issues'] }),
      ]),
  });
}

export interface HistoryFilters {
  page: number;
  eventType: HistoryEventType | null;
}

export function useHistory({ page, eventType }: HistoryFilters) {
  const params = new URLSearchParams({ page: String(page), pageSize: '25' });
  if (eventType) params.set('eventType', eventType);
  return useQuery({
    queryKey: ['history', page, eventType],
    queryFn: () => apiGet<HistoryPage>(`/api/v1/history?${params.toString()}`),
    placeholderData: keepPreviousData,
  });
}

export function useManualImportScan() {
  return useMutation({
    mutationFn: (source: { path?: string; downloadId?: number }) => {
      const params = new URLSearchParams();
      if (source.downloadId !== undefined) params.set('downloadId', String(source.downloadId));
      if (source.path) params.set('path', source.path);
      return apiGet<ManualImportScan>(`/api/v1/manualimport?${params.toString()}`);
    },
  });
}

export function useManualImport() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      downloadId: number | null;
      mode: 'move' | 'copy' | null;
      files: { path: string; issueId: number; quality: string }[];
    }) => apiPost<ManualImportOutcome[]>('/api/v1/manualimport', body),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: QUEUE_KEY }),
        client.invalidateQueries({ queryKey: ['issues'] }),
        client.invalidateQueries({ queryKey: ['magazines'] }),
      ]),
  });
}
