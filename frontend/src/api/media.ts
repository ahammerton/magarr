import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiDelete, apiGet, apiPost, apiPut } from './client';
import type { MediaSettings, RemotePathMapping } from './types';

export function useMediaSettings() {
  return useQuery({ queryKey: ['mediaSettings'], queryFn: () => apiGet<MediaSettings>('/api/v1/config/mediamanagement') });
}

export function useSaveMediaSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: MediaSettings) => apiPut<MediaSettings>('/api/v1/config/mediamanagement', body),
    onSuccess: (saved) => client.setQueryData(['mediaSettings'], saved),
  });
}

export function useRemotePathMappings() {
  return useQuery({
    queryKey: ['remotePathMappings'],
    queryFn: () => apiGet<RemotePathMapping[]>('/api/v1/remotepathmapping'),
  });
}

export function useAddRemotePathMapping() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: Omit<RemotePathMapping, 'id'>) => apiPost<RemotePathMapping>('/api/v1/remotepathmapping', body),
    onSuccess: () => client.invalidateQueries({ queryKey: ['remotePathMappings'] }),
  });
}

export function useDeleteRemotePathMapping() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiDelete(`/api/v1/remotepathmapping/${id}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ['remotePathMappings'] }),
  });
}
