import { Button, Center, Loader, Stack, Text } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { initialize } from './api/client';
import { t } from './i18n';

/** Fetches /initialize.json (which carries the API key) before rendering the app. */
export function Boot({ children }: { children: ReactNode }) {
  const { isPending, isError, refetch } = useQuery({
    queryKey: ['initialize'],
    queryFn: initialize,
    staleTime: Infinity,
    retry: 1,
  });

  if (isPending) {
    return (
      <Center h="100vh">
        <Stack align="center">
          <Loader />
          <Text c="dimmed">{t('boot.loading')}</Text>
        </Stack>
      </Center>
    );
  }
  if (isError) {
    return (
      <Center h="100vh">
        <Stack align="center">
          <Text c="red">{t('boot.error')}</Text>
          <Button onClick={() => void refetch()}>{t('boot.retry')}</Button>
        </Stack>
      </Center>
    );
  }
  return children;
}
