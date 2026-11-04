import { Alert, Center, Loader } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';
import type { ReactNode } from 'react';

import { t } from '../i18n';

interface QueryStateProps {
  isPending: boolean;
  error: Error | null;
  children: () => ReactNode;
}

/** Spinner while loading, an alert on error, otherwise the content. */
export function QueryState({ isPending, error, children }: QueryStateProps) {
  if (isPending) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }
  if (error) {
    return (
      <Alert color="red" icon={<IconAlertTriangle />} title={t('common.loadError')}>
        {error.message}
      </Alert>
    );
  }
  return <>{children()}</>;
}
