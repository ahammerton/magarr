import { useQuery } from '@tanstack/react-query';

import { apiGet } from './client';

export interface SystemStatus {
  appName: string;
  version: string;
  startTime: string;
  uptimeSeconds: number;
  isDocker: boolean;
  osName: string;
  osVersion: string;
  pythonVersion: string;
  databaseType: string;
  databaseVersion: string;
  databaseMigration: string | null;
  appDataDir: string;
  authentication: 'apiKey' | 'basic';
}

export function useSystemStatus() {
  return useQuery({
    queryKey: ['system', 'status'],
    queryFn: () => apiGet<SystemStatus>('/api/v1/system/status'),
  });
}
