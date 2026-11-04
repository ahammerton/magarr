import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from './client';
import type {
  NamingConfig,
  Protocol,
  NamingPreview,
  Quality,
  QualityProfile,
  QualityProfileItem,
  RootFolder,
  ScanResult,
  UnmappedFile,
} from './types';

const keys = {
  rootFolders: ['rootFolders'] as const,
  profiles: ['qualityProfiles'] as const,
  qualities: ['qualities'] as const,
  naming: ['naming'] as const,
  unmapped: ['unmapped'] as const,
};

export function useRootFolders() {
  return useQuery({
    queryKey: keys.rootFolders,
    queryFn: () => apiGet<RootFolder[]>('/api/v1/rootfolder'),
  });
}

export function useAddRootFolder() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (path: string) => apiPost<RootFolder>('/api/v1/rootfolder', { path }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.rootFolders }),
  });
}

export function useSetDefaultRootFolder() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiPatch<RootFolder>(`/api/v1/rootfolder/${id}`, { isDefault: true }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.rootFolders }),
  });
}

export function useDeleteRootFolder() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiDelete(`/api/v1/rootfolder/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.rootFolders }),
  });
}

export function useQualities() {
  return useQuery({
    queryKey: keys.qualities,
    queryFn: () => apiGet<Quality[]>('/api/v1/quality'),
    staleTime: Infinity,
  });
}

export function useQualityProfiles() {
  return useQuery({
    queryKey: keys.profiles,
    queryFn: () => apiGet<QualityProfile[]>('/api/v1/qualityprofile'),
  });
}

export interface ProfileBody {
  name: string;
  items: QualityProfileItem[];
  protocols: Protocol[];
  mustContain: string[];
  mustNotContain: string[];
}

export function useSaveQualityProfile() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: ProfileBody & { id?: number }) =>
      id === undefined
        ? apiPost<QualityProfile>('/api/v1/qualityprofile', body)
        : apiPut<QualityProfile>(`/api/v1/qualityprofile/${id}`, body),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.profiles }),
  });
}

export function useDeleteQualityProfile() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiDelete(`/api/v1/qualityprofile/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.profiles }),
  });
}

export function useNamingConfig() {
  return useQuery({ queryKey: keys.naming, queryFn: () => apiGet<NamingConfig>('/api/v1/config/naming') });
}

export function useSaveNamingConfig() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (config: NamingConfig) => apiPut<NamingConfig>('/api/v1/config/naming', config),
    onSuccess: (saved) => client.setQueryData(keys.naming, saved),
  });
}

export function useNamingPreview() {
  return useMutation({
    mutationFn: (config: NamingConfig) =>
      apiPost<NamingPreview>('/api/v1/config/naming/preview', config),
  });
}

export function useUnmappedFiles() {
  return useQuery({
    queryKey: keys.unmapped,
    queryFn: () => apiGet<UnmappedFile[]>('/api/v1/library/unmapped'),
  });
}

export function useLibraryScan() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (rootFolderId?: number) =>
      apiPost<ScanResult[]>('/api/v1/library/scan', { rootFolderId }),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: keys.unmapped }),
        client.invalidateQueries({ queryKey: ['magazines'] }),
        client.invalidateQueries({ queryKey: ['issues'] }),
      ]),
  });
}
