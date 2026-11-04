import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiDelete, apiGet, apiPost, apiUpload } from './client';
import type { Backup, Health, LogPage, Task, TaskRun } from './types';

const keys = {
  tasks: ['tasks'] as const,
  health: ['health'] as const,
  backups: ['backups'] as const,
};

export function useTasks() {
  // Short tasks finish within a second or two of "Run now"; keep the list current.
  return useQuery({ queryKey: keys.tasks, queryFn: () => apiGet<Task[]>('/api/v1/system/task'), refetchInterval: 5000 });
}

export function useTaskHistory(name: string | null) {
  return useQuery({
    queryKey: [...keys.tasks, name, 'history'],
    queryFn: () => apiGet<TaskRun[]>(`/api/v1/system/task/${name}/history`),
    enabled: name !== null,
  });
}

export function useRunTask() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => apiPost<{ message: string }>(`/api/v1/system/task/${name}/run`),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.tasks }),
  });
}

export function useHealth() {
  return useQuery({ queryKey: keys.health, queryFn: () => apiGet<Health>('/api/v1/system/health'), refetchInterval: 60_000 });
}

export function useCheckHealth() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiGet<Health>('/api/v1/system/health?refresh=true'),
    onSuccess: (health) => client.setQueryData(keys.health, health),
  });
}

export function useBackups() {
  return useQuery({ queryKey: keys.backups, queryFn: () => apiGet<Backup[]>('/api/v1/system/backup') });
}

export function useCreateBackup() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => apiPost<Backup>('/api/v1/system/backup'),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.backups }),
  });
}

export function useDeleteBackup() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => apiDelete(`/api/v1/system/backup/${encodeURIComponent(name)}`),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.backups }),
  });
}

export function useRestoreBackup() {
  return useMutation({
    mutationFn: (source: { name: string } | { file: File }) =>
      'name' in source
        ? apiPost<{ message: string }>(`/api/v1/system/backup/${encodeURIComponent(source.name)}/restore`)
        : apiUpload<{ message: string }>('/api/v1/system/backup/upload', source.file, 'application/zip'),
  });
}

export function fetchLogs(after: number, level: string): Promise<LogPage> {
  return apiGet<LogPage>(`/api/v1/system/logs?after=${after}&level=${level}&limit=500`);
}
