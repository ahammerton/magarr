import { Anchor, Button, Checkbox, Group, Pagination, SegmentedControl, Select, Stack, Table, Text } from '@mantine/core';
import { IconSearch } from '@tabler/icons-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { useWanted, useWantedSearch } from '../../api/automation';
import { useBulkUpdateIssues, useMagazines } from '../../api/magazines';
import type { MagazineIssue } from '../../api/types';
import { PageHeader } from '../../components/PageHeader';
import { QueryState } from '../../components/QueryState';
import { DownloadBadge, StatusBadge } from '../../components/StatusBadge';
import { t } from '../../i18n';
import { notifyError, notifySuccess } from '../../notify';

const PAGE_SIZE = 50;
type Status = 'wanted' | 'missing';

function when(value: string | null): string {
  return value ? new Date(value).toLocaleString() : t('wanted.never');
}

export function WantedPage() {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<Status>('wanted');
  const [magazineId, setMagazineId] = useState<number | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const magazines = useMagazines();
  const { data, isPending, error } = useWanted({ page, pageSize: PAGE_SIZE, status, magazineId });
  const search = useWantedSearch();
  const bulk = useBulkUpdateIssues();

  const records = useMemo(() => data?.records ?? [], [data]);
  const chosen = records.filter((r) => selected.has(r.id));
  const allSelected = records.length > 0 && chosen.length === records.length;
  const reset = () => {
    setSelected(new Set());
    setPage(1);
  };

  const toggle = (id: number) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const searchSelected = () =>
    search.mutate(
      chosen.map((r) => r.id),
      {
        onSuccess: ({ queued }) => {
          notifySuccess(t('wanted.searchQueued', { count: queued }));
          setSelected(new Set());
        },
        onError: notifyError,
      },
    );

  const setMonitored = (monitored: boolean) =>
    bulk.mutate(
      { ids: chosen.map((r) => r.id), monitored },
      { onSuccess: () => setSelected(new Set()), onError: notifyError },
    );

  return (
    <Stack gap="lg">
      <PageHeader title={t('nav.wanted')}>
        <Select
          aria-label={t('wanted.magazine')}
          placeholder={t('wanted.magazine.all')}
          clearable
          searchable
          data={(magazines.data ?? []).map((m) => ({ value: String(m.id), label: m.title }))}
          value={magazineId === null ? null : String(magazineId)}
          onChange={(value) => {
            setMagazineId(value ? Number(value) : null);
            reset();
          }}
          w={240}
        />
        <SegmentedControl
          value={status}
          onChange={(value) => {
            setStatus(value as Status);
            reset();
          }}
          data={[
            { value: 'wanted', label: t('status.issue.wanted') },
            { value: 'missing', label: t('wanted.unmonitored') },
          ]}
        />
      </PageHeader>
      <Text size="sm" c="dimmed">
        {t(status === 'wanted' ? 'wanted.help' : 'wanted.help.missing')}
      </Text>
      <QueryState isPending={isPending} error={error}>
        {() =>
          records.length === 0 ? (
            <Text c="dimmed">{t(status === 'wanted' ? 'wanted.empty' : 'wanted.empty.missing')}</Text>
          ) : (
            <Stack>
              <Group gap="xs">
                <Button
                  size="xs"
                  leftSection={<IconSearch size={14} />}
                  disabled={chosen.length === 0 || status !== 'wanted'}
                  loading={search.isPending}
                  onClick={searchSelected}
                >
                  {t('wanted.searchSelected', { count: chosen.length })}
                </Button>
                <Button
                  size="xs"
                  variant="default"
                  disabled={chosen.length === 0}
                  loading={bulk.isPending}
                  onClick={() => setMonitored(status !== 'wanted')}
                >
                  {t(status === 'wanted' ? 'issues.bulk.unmonitor' : 'issues.bulk.wanted')}
                </Button>
                <Text size="sm" c="dimmed">
                  {t('wanted.total', { count: data!.total })}
                </Text>
              </Group>
              <Table.ScrollContainer minWidth={760}>
                <Table verticalSpacing="xs" striped>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th w={40}>
                        <Checkbox
                          aria-label={t('issues.selectAll')}
                          checked={allSelected}
                          indeterminate={chosen.length > 0 && !allSelected}
                          onChange={() =>
                            setSelected(allSelected ? new Set() : new Set(records.map((r) => r.id)))
                          }
                        />
                      </Table.Th>
                      <Table.Th>{t('wanted.column.magazine')}</Table.Th>
                      <Table.Th>{t('issues.column.number')}</Table.Th>
                      <Table.Th>{t('issues.column.published')}</Table.Th>
                      <Table.Th>{t('issues.column.status')}</Table.Th>
                      <Table.Th>{t('wanted.column.lastSearched')}</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {records.map((issue: MagazineIssue) => (
                      <Table.Tr key={issue.id} data-testid="wanted-row">
                        <Table.Td>
                          <Checkbox
                            aria-label={t('issues.select', { issue: `${issue.magazineTitle} ${issue.issueNumber}` })}
                            checked={selected.has(issue.id)}
                            onChange={() => toggle(issue.id)}
                          />
                        </Table.Td>
                        <Table.Td>
                          <Anchor component={Link} to={`/magazine/${issue.magazineId}`} size="sm">
                            {issue.magazineTitle}
                          </Anchor>
                          {!issue.magazineMonitored && (
                            <Text span size="xs" c="dimmed" ml={6}>
                              {t('wanted.magazineUnmonitored')}
                            </Text>
                          )}
                        </Table.Td>
                        <Table.Td>{issue.issueNumber}</Table.Td>
                        <Table.Td style={{ whiteSpace: 'nowrap' }}>{issue.publishDate ?? '—'}</Table.Td>
                        <Table.Td>
                          {issue.download ? <DownloadBadge download={issue.download} /> : <StatusBadge status={issue.status} />}
                        </Table.Td>
                        <Table.Td style={{ whiteSpace: 'nowrap' }}>
                          <Text size="sm" c={issue.lastSearchedAt ? undefined : 'dimmed'}>
                            {when(issue.lastSearchedAt)}
                          </Text>
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Table.ScrollContainer>
              <Group justify="center">
                <Pagination
                  total={Math.max(1, Math.ceil(data!.total / data!.pageSize))}
                  value={page}
                  onChange={(next) => {
                    setPage(next);
                    setSelected(new Set());
                  }}
                />
              </Group>
            </Stack>
          )
        }
      </QueryState>
    </Stack>
  );
}
