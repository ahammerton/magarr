import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiGet, apiPost, apiPut } from './client';
import type { Automation, AutomationSettings, MagazineIssue, WantedPage } from './types';

const keys = {
  settings: ['automation'] as const,
  wanted: ['issues', 'wanted'] as const,
  calendar: ['issues', 'calendar'] as const,
};

export function useAutomation() {
  // The job list shows when each job last ran, so keep it fresh while the page is open.
  return useQuery({
    queryKey: keys.settings,
    queryFn: () => apiGet<Automation>('/api/v1/config/automation'),
    refetchInterval: 60_000,
  });
}

export function useSaveAutomation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: AutomationSettings) => apiPut<Automation>('/api/v1/config/automation', body),
    onSuccess: (saved) => client.setQueryData(keys.settings, saved),
  });
}

export interface WantedQuery {
  page: number;
  pageSize: number;
  status: 'wanted' | 'missing';
  magazineId: number | null;
}

export function useWanted({ page, pageSize, status, magazineId }: WantedQuery) {
  const params = new URLSearchParams({ page: String(page), pageSize: String(pageSize), status });
  if (magazineId !== null) params.set('magazineId', String(magazineId));
  return useQuery({
    queryKey: [...keys.wanted, page, pageSize, status, magazineId],
    queryFn: () => apiGet<WantedPage>(`/api/v1/wanted?${params}`),
    placeholderData: keepPreviousData,
  });
}

export function useWantedSearch() {
  return useMutation({
    mutationFn: (issueIds: number[]) =>
      apiPost<{ queued: number }>('/api/v1/wanted/search', { issueIds }),
  });
}

/** ``start`` and ``end`` are inclusive YYYY-MM-DD dates. */
export function useCalendar(start: string, end: string, unmonitored: boolean) {
  const params = new URLSearchParams({ start, end, unmonitored: String(unmonitored) });
  return useQuery({
    queryKey: [...keys.calendar, start, end, unmonitored],
    queryFn: () => apiGet<MagazineIssue[]>(`/api/v1/calendar?${params}`),
    placeholderData: keepPreviousData,
  });
}
