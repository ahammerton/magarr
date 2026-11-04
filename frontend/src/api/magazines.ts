import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from './client';
import type {
  CsvImportResult,
  Issue,
  IssueInput,
  IssueStatus,
  Magazine,
  MagazineInput,
  SearchResult,
} from './types';

export const keys = {
  magazines: ['magazines'] as const,
  magazine: (id: number) => ['magazines', id] as const,
  issues: (magazineId: number) => ['issues', magazineId] as const,
};

export function useMagazines() {
  return useQuery({ queryKey: keys.magazines, queryFn: () => apiGet<Magazine[]>('/api/v1/magazine') });
}

export function useMagazine(id: number) {
  return useQuery({
    queryKey: keys.magazine(id),
    queryFn: () => apiGet<Magazine>(`/api/v1/magazine/${id}`),
  });
}

const ACTIVE = new Set(['queued', 'downloading', 'paused', 'warning']);

export function useIssues(magazineId: number, options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: keys.issues(magazineId),
    enabled: options.enabled ?? true,
    queryFn: () => apiGet<Issue[]>(`/api/v1/issue?magazineId=${magazineId}`),
    // Refresh while something is downloading so progress updates on issue rows.
    refetchInterval: (query) =>
      query.state.data?.some((i) => i.download && ACTIVE.has(i.download.status)) ? 5000 : false,
  });
}

/** Issue changes alter magazine statistics too, so refresh both. */
function useInvalidateLibrary() {
  const client = useQueryClient();
  return () =>
    Promise.all([
      client.invalidateQueries({ queryKey: keys.magazines }),
      client.invalidateQueries({ queryKey: ['issues'] }),
    ]);
}

export function useCreateMagazine() {
  const invalidate = useInvalidateLibrary();
  return useMutation({
    mutationFn: (input: MagazineInput & { title: string }) =>
      apiPost<Magazine>('/api/v1/magazine', input),
    onSuccess: invalidate,
  });
}

export function useUpdateMagazine(id: number) {
  const invalidate = useInvalidateLibrary();
  return useMutation({
    mutationFn: (input: MagazineInput) => apiPatch<Magazine>(`/api/v1/magazine/${id}`, input),
    onSuccess: invalidate,
  });
}

export function useDeleteMagazine() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiDelete(`/api/v1/magazine/${id}`),
    onSuccess: (_data, id) => {
      client.removeQueries({ queryKey: keys.magazine(id) });
      client.removeQueries({ queryKey: keys.issues(id) });
      return client.invalidateQueries({ queryKey: keys.magazines, exact: true });
    },
  });
}

export function useGenerateIssues(magazineId: number) {
  const invalidate = useInvalidateLibrary();
  return useMutation({
    mutationFn: (body: { start: string | null; count: number; monitored: boolean; firstNumber: number | null }) =>
      apiPost<{ created: Issue[]; skipped: number }>(
        `/api/v1/magazine/${magazineId}/generate-issues`,
        body,
      ),
    onSuccess: invalidate,
  });
}

export function useCreateIssue(magazineId: number) {
  const invalidate = useInvalidateLibrary();
  return useMutation({
    mutationFn: (input: IssueInput & { issueNumber: string }) =>
      apiPost<Issue>('/api/v1/issue', { ...input, magazineId }),
    onSuccess: invalidate,
  });
}

export function useUpdateIssue() {
  const invalidate = useInvalidateLibrary();
  return useMutation({
    mutationFn: ({ id, ...input }: IssueInput & { id: number }) =>
      apiPatch<Issue>(`/api/v1/issue/${id}`, input),
    onSuccess: invalidate,
  });
}

export function useBulkUpdateIssues() {
  const invalidate = useInvalidateLibrary();
  return useMutation({
    mutationFn: (body: { ids: number[]; monitored?: boolean; status?: IssueStatus }) =>
      apiPost<Issue[]>('/api/v1/issue/bulk', body),
    onSuccess: invalidate,
  });
}

export function useDeleteIssue() {
  const invalidate = useInvalidateLibrary();
  return useMutation({
    mutationFn: (id: number) => apiDelete(`/api/v1/issue/${id}`),
    onSuccess: invalidate,
  });
}

export function useIssueSearch(issueId: number | null) {
  return useQuery({
    queryKey: ['search', issueId],
    queryFn: () => apiPost<SearchResult>(`/api/v1/issue/${issueId}/search`),
    enabled: issueId !== null,
    staleTime: 0,
    gcTime: 0,
  });
}

export function useCsvImport() {
  const invalidate = useInvalidateLibrary();
  return useMutation({
    mutationFn: (body: { csv: string; createMissing: boolean; monitored: boolean }) =>
      apiPost<CsvImportResult>('/api/v1/magazine/import', body),
    onSuccess: invalidate,
  });
}

export interface MagazineEditorChanges {
  monitored?: boolean;
  qualityProfileId?: number;
  rootFolderId?: number;
  grabNewSpecials?: boolean;
}

export function useMagazineEditor() {
  const invalidate = useInvalidateLibrary();
  return useMutation({
    mutationFn: (body: { ids: number[] } & MagazineEditorChanges) => apiPut<Magazine[]>('/api/v1/magazine/editor', body),
    onSuccess: invalidate,
  });
}

export function useDeleteMagazines() {
  const invalidate = useInvalidateLibrary();
  return useMutation({
    mutationFn: (ids: number[]) => apiPost<void>('/api/v1/magazine/editor/delete', { ids }),
    onSuccess: invalidate,
  });
}
