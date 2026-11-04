import { Anchor, Badge, Group, Pagination, Select, Stack, Table, Text } from '@mantine/core';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { useHistory } from '../../api/activity';
import type { HistoryEventType, HistoryRecord } from '../../api/types';
import { PageHeader } from '../../components/PageHeader';
import { QueryState } from '../../components/QueryState';
import { t } from '../../i18n';

const EVENTS: HistoryEventType[] = [
  'grabbed',
  'download_completed',
  'download_failed',
  'imported',
  'upgraded',
  'import_failed',
  'file_deleted',
];
const COLORS: Record<HistoryEventType, string> = {
  grabbed: 'blue',
  download_completed: 'violet',
  download_failed: 'red',
  imported: 'teal',
  upgraded: 'teal',
  import_failed: 'orange',
  file_deleted: 'gray',
};

function detail(record: HistoryRecord): string {
  const d = record.data;
  const pick = (key: string) => (typeof d[key] === 'string' ? (d[key] as string) : null);
  if (record.eventType === 'grabbed' && pick('source') && pick('client')) {
    // e.g. "RSS sync → SABnzbd": how it was found, and where it went.
    return `${pick('source')} → ${pick('client')}`;
  }
  return pick('imported_path') ?? pick('message') ?? pick('output_path') ?? pick('result') ?? pick('client') ?? '';
}

export function HistoryPage() {
  const [page, setPage] = useState(1);
  const [eventType, setEventType] = useState<HistoryEventType | null>(null);
  const { data, isPending, error } = useHistory({ page, eventType });

  return (
    <Stack gap="lg">
      <PageHeader title={t('nav.activity.history')}>
        <Select
          aria-label={t('history.filter')}
          placeholder={t('history.filter.all')}
          clearable
          data={EVENTS.map((e) => ({ value: e, label: t(`history.event.${e}`) }))}
          value={eventType}
          onChange={(value) => {
            setEventType(value as HistoryEventType | null);
            setPage(1);
          }}
          w={220}
        />
      </PageHeader>
      <QueryState isPending={isPending} error={error}>
        {() =>
          data!.records.length === 0 ? (
            <Text c="dimmed">{t('history.empty')}</Text>
          ) : (
            <Stack>
              <Table.ScrollContainer minWidth={900}>
                <Table verticalSpacing="xs" striped>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>{t('history.column.event')}</Table.Th>
                      <Table.Th>{t('queue.column.issue')}</Table.Th>
                      <Table.Th>{t('search.column.title')}</Table.Th>
                      <Table.Th>{t('history.column.detail')}</Table.Th>
                      <Table.Th>{t('history.column.date')}</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {data!.records.map((record) => (
                      <Table.Tr key={record.id} data-testid="history-row">
                        <Table.Td>
                          <Badge color={COLORS[record.eventType]} variant="light" style={{ minWidth: 'max-content' }}>
                            {t(`history.event.${record.eventType}`)}
                          </Badge>
                        </Table.Td>
                        <Table.Td>
                          {record.magazineId ? (
                            <Anchor component={Link} to={`/magazine/${record.magazineId}`} size="sm">
                              {record.magazineTitle} · {record.issueNumber}
                            </Anchor>
                          ) : (
                            '—'
                          )}
                        </Table.Td>
                        <Table.Td>
                          <Text size="sm" ff="monospace" style={{ overflowWrap: 'anywhere' }}>
                            {record.sourceTitle}
                          </Text>
                        </Table.Td>
                        <Table.Td>
                          <Text size="xs" c="dimmed" style={{ overflowWrap: 'anywhere' }}>
                            {detail(record)}
                          </Text>
                        </Table.Td>
                        <Table.Td style={{ whiteSpace: 'nowrap' }}>{new Date(record.date).toLocaleString()}</Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Table.ScrollContainer>
              <Group justify="center">
                <Pagination total={Math.max(1, Math.ceil(data!.total / data!.pageSize))} value={page} onChange={setPage} />
              </Group>
            </Stack>
          )
        }
      </QueryState>
    </Stack>
  );
}
