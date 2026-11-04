import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from './client';
import type { Category, Indexer, IndexerInput, ProwlarrConfig, SyncResult, TestResult } from './types';

const keys = {
  indexers: ['indexers'] as const,
  categories: ['indexerCategories'] as const,
  prowlarr: ['prowlarr'] as const,
};

/** Value the API uses for a stored secret; sending it back leaves the secret unchanged. */
export const MASKED_KEY = '********';

export function useIndexers() {
  return useQuery({ queryKey: keys.indexers, queryFn: () => apiGet<Indexer[]>('/api/v1/indexer') });
}

export function useIndexerCategories() {
  return useQuery({
    queryKey: keys.categories,
    queryFn: () => apiGet<Category[]>('/api/v1/indexer/categories'),
    staleTime: Infinity,
  });
}

export function useSaveIndexer() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...input }: IndexerInput & { id?: number }) =>
      id === undefined
        ? apiPost<Indexer>('/api/v1/indexer', input)
        : apiPatch<Indexer>(`/api/v1/indexer/${id}`, input),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.indexers }),
  });
}

export function useToggleIndexer() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      apiPatch<Indexer>(`/api/v1/indexer/${id}`, { enabled }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.indexers }),
  });
}

export function useDeleteIndexer() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiDelete(`/api/v1/indexer/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.indexers }),
  });
}

/** Test unsaved settings (pass ``id`` when editing so a masked key resolves to the stored one). */
export function useTestIndexerSettings() {
  return useMutation({
    mutationFn: (input: IndexerInput & { id?: number }) => apiPost<TestResult>('/api/v1/indexer/test', input),
  });
}

export function useTestSavedIndexer() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiPost<TestResult>(`/api/v1/indexer/${id}/test`),
    onSettled: () => client.invalidateQueries({ queryKey: keys.indexers }),
  });
}

export function useProwlarrConfig() {
  return useQuery({ queryKey: keys.prowlarr, queryFn: () => apiGet<ProwlarrConfig>('/api/v1/config/prowlarr') });
}

export function useSaveProwlarrConfig() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { url: string; apiKey: string }) => apiPut<ProwlarrConfig>('/api/v1/config/prowlarr', body),
    onSuccess: (saved) => client.setQueryData(keys.prowlarr, saved),
  });
}

export function useTestProwlarr() {
  return useMutation({
    mutationFn: (body: { url: string; apiKey: string }) => apiPost<TestResult>('/api/v1/config/prowlarr/test', body),
  });
}

export function useSyncProwlarr() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<SyncResult>('/api/v1/indexer/sync-prowlarr'),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: keys.indexers }),
        client.invalidateQueries({ queryKey: keys.prowlarr }),
      ]),
  });
}
