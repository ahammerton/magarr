import { Button, Code, Stack, Table, Text } from '@mantine/core';
import { IconRefresh } from '@tabler/icons-react';

import { useLibraryScan, useUnmappedFiles } from '../../api/settings';
import { PageHeader } from '../../components/PageHeader';
import { QueryState } from '../../components/QueryState';
import { formatBytes } from '../../format';
import { t } from '../../i18n';
import { notifyError } from '../../notify';

export function UnmappedPage() {
  const { data, isPending, error } = useUnmappedFiles();
  const scan = useLibraryScan();

  return (
    <Stack gap="lg">
      <PageHeader title={t('unmapped.title')}>
        <Button
          variant="default"
          leftSection={<IconRefresh size={16} />}
          loading={scan.isPending}
          onClick={() => scan.mutate(undefined, { onError: notifyError })}
        >
          {t('library.scan')}
        </Button>
      </PageHeader>
      <Text size="sm" c="dimmed">
        {t('unmapped.help')}
      </Text>
      <QueryState isPending={isPending} error={error}>
        {() =>
          data!.length === 0 ? (
            <Text c="dimmed">{t('unmapped.empty')}</Text>
          ) : (
            <Table.ScrollContainer minWidth={640}>
              <Table verticalSpacing="xs">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>{t('unmapped.column.path')}</Table.Th>
                    <Table.Th>{t('unmapped.column.reason')}</Table.Th>
                    <Table.Th ta="right">{t('unmapped.column.size')}</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {data!.map((file) => (
                    <Table.Tr key={file.id}>
                      <Table.Td>
                        <Text size="xs" c="dimmed">
                          {file.rootFolderPath}
                        </Text>
                        <Code>{file.relativePath}</Code>
                      </Table.Td>
                      <Table.Td>{file.reason}</Table.Td>
                      <Table.Td ta="right">{formatBytes(file.size)}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )
        }
      </QueryState>
    </Stack>
  );
}
