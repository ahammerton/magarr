import { Alert, Badge, Card, Skeleton, Stack, Table, Title } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';
import type { ReactNode } from 'react';

import { useSystemStatus } from '../../api/system';
import { formatUptime } from '../../format';
import { t, type MessageKey } from '../../i18n';

export function StatusPage() {
  const { data, isPending, isError } = useSystemStatus();

  let body: ReactNode;
  if (isPending) {
    body = <Skeleton height={320} />;
  } else if (isError) {
    body = (
      <Alert color="red" icon={<IconAlertTriangle />}>
        {t('status.loadError')}
      </Alert>
    );
  } else {
    const rows: [MessageKey, ReactNode][] = [
      ['status.version', <Badge key="v" variant="light">{data.version}</Badge>],
      ['status.python', data.pythonVersion],
      ['status.os', `${data.osName} ${data.osVersion}`],
      ['status.docker', data.isDocker ? t('common.yes') : t('common.no')],
      ['status.database', `${data.databaseType} ${data.databaseVersion}`],
      ['status.migration', data.databaseMigration ?? t('common.none')],
      ['status.appData', data.appDataDir],
      ['status.startTime', new Date(data.startTime).toLocaleString()],
      ['status.uptime', formatUptime(data.uptimeSeconds)],
      [
        'status.authentication',
        data.authentication === 'basic' ? t('status.auth.basic') : t('status.auth.apiKey'),
      ],
    ];
    body = (
      <Table variant="vertical" layout="fixed" withTableBorder={false}>
        <Table.Tbody>
          {rows.map(([label, value]) => (
            <Table.Tr key={label}>
              <Table.Th w={220}>{t(label)}</Table.Th>
              <Table.Td>{value}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    );
  }

  return (
    <Stack gap="lg">
      <Title order={2}>{t('status.title')}</Title>
      <Card withBorder padding="lg">
        <Title order={4} mb="md">
          {t('status.about')}
        </Title>
        {body}
      </Card>
    </Stack>
  );
}
