import { ActionIcon, Badge, Button, Checkbox, Group, SegmentedControl, Stack, Table, Text, Tooltip } from '@mantine/core';
import { IconBookmark, IconBookmarkOff, IconEdit, IconSearch, IconTrash } from '@tabler/icons-react';
import { useMemo, useState } from 'react';

import { useBulkUpdateIssues, useDeleteIssue, useUpdateIssue } from '../../api/magazines';
import type { Issue, IssueStatus } from '../../api/types';
import { ConfirmModal } from '../../components/ConfirmModal';
import { DownloadBadge, StatusBadge } from '../../components/StatusBadge';
import { formatBytes, formatDate } from '../../format';
import { t } from '../../i18n';
import { notifyError } from '../../notify';
import { IssueModal } from './MagazineModals';
import { SearchModal } from './SearchModal';

type Filter = 'all' | IssueStatus;
const FILTERS: Filter[] = ['all', 'wanted', 'missing', 'downloaded', 'ignored'];

export function IssueTable({ magazineId, issues }: { magazineId: number; issues: Issue[] }) {
  const [filter, setFilter] = useState<Filter>('all');
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [editing, setEditing] = useState<Issue | null>(null);
  const [deleting, setDeleting] = useState<Issue | null>(null);
  const [searching, setSearching] = useState<Issue | null>(null);
  const bulk = useBulkUpdateIssues();
  const update = useUpdateIssue();
  const remove = useDeleteIssue();

  const visible = useMemo(
    () => (filter === 'all' ? issues : issues.filter((i) => i.status === filter)),
    [issues, filter],
  );
  const visibleSelected = visible.filter((i) => selected.has(i.id));
  const allSelected = visible.length > 0 && visibleSelected.length === visible.length;

  const toggle = (id: number) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const toggleAll = () => setSelected(allSelected ? new Set() : new Set(visible.map((i) => i.id)));

  const applyBulk = (body: { monitored?: boolean; status?: IssueStatus }) =>
    bulk.mutate(
      { ids: visibleSelected.map((i) => i.id), ...body },
      { onSuccess: () => setSelected(new Set()), onError: notifyError },
    );

  const counts = Object.fromEntries(
    FILTERS.map((f) => [f, f === 'all' ? issues.length : issues.filter((i) => i.status === f).length]),
  ) as Record<Filter, number>;

  return (
    <Stack gap="sm">
      <Group justify="space-between" wrap="wrap">
        <SegmentedControl
          size="xs"
          value={filter}
          onChange={(value) => setFilter(value as Filter)}
          data={FILTERS.map((f) => ({ value: f, label: `${t(`issues.filter.${f}`)} (${counts[f]})` }))}
        />
        {visibleSelected.length > 0 && (
          <Group gap="xs">
            <Text size="sm" c="dimmed">
              {t('issues.selected', { count: visibleSelected.length })}
            </Text>
            <Button size="xs" loading={bulk.isPending} onClick={() => applyBulk({ status: 'wanted' })}>
              {t('issues.bulk.wanted')}
            </Button>
            <Button size="xs" variant="default" onClick={() => applyBulk({ monitored: false })}>
              {t('issues.bulk.unmonitor')}
            </Button>
            <Button size="xs" variant="default" onClick={() => applyBulk({ status: 'ignored' })}>
              {t('issues.bulk.ignore')}
            </Button>
          </Group>
        )}
      </Group>

      {issues.length === 0 ? (
        <Text c="dimmed" py="lg">
          {t('issues.empty')}
        </Text>
      ) : (
        <Table.ScrollContainer minWidth={720}>
          <Table highlightOnHover verticalSpacing={6}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th w={36}>
                  <Checkbox
                    aria-label={t('issues.selectAll')}
                    checked={allSelected}
                    indeterminate={visibleSelected.length > 0 && !allSelected}
                    onChange={toggleAll}
                  />
                </Table.Th>
                <Table.Th w={36} />
                <Table.Th>{t('issues.column.number')}</Table.Th>
                <Table.Th>{t('issues.column.title')}</Table.Th>
                <Table.Th>{t('issues.column.published')}</Table.Th>
                <Table.Th>{t('issues.column.status')}</Table.Th>
                <Table.Th>{t('issues.column.file')}</Table.Th>
                <Table.Th w={110} />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {visible.map((issue) => (
                <Table.Tr key={issue.id} data-testid="issue-row">
                  <Table.Td>
                    <Checkbox
                      aria-label={t('issues.select', { issue: issue.issueNumber })}
                      checked={selected.has(issue.id)}
                      onChange={() => toggle(issue.id)}
                    />
                  </Table.Td>
                  <Table.Td>
                    <Tooltip label={issue.monitored ? t('issues.unmonitor') : t('issues.monitor')}>
                      <ActionIcon
                        variant="subtle"
                        color={issue.monitored ? 'violet' : 'gray'}
                        aria-label={
                          issue.monitored
                            ? t('issues.unmonitorIssue', { issue: issue.issueNumber })
                            : t('issues.monitorIssue', { issue: issue.issueNumber })
                        }
                        onClick={() =>
                          update.mutate({ id: issue.id, monitored: !issue.monitored }, { onError: notifyError })
                        }
                      >
                        {issue.monitored ? <IconBookmark size={18} /> : <IconBookmarkOff size={18} />}
                      </ActionIcon>
                    </Tooltip>
                  </Table.Td>
                  <Table.Td fw={500}>{issue.issueNumber}</Table.Td>
                  <Table.Td>{issue.title ?? ''}</Table.Td>
                  <Table.Td>{formatDate(issue.publishDate)}</Table.Td>
                  <Table.Td>
                    <Group gap={6} wrap="nowrap">
                      <StatusBadge status={issue.status} />
                      {issue.download && <DownloadBadge download={issue.download} />}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    {issue.file ? (
                      <Tooltip label={issue.file.relativePath}>
                        <Group gap={6}>
                          <Badge variant="outline" size="sm">
                            {issue.file.format.toUpperCase()}
                          </Badge>
                          <Text size="xs" c="dimmed">
                            {formatBytes(issue.file.size)}
                          </Text>
                        </Group>
                      </Tooltip>
                    ) : (
                      '—'
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Group gap={2} justify="flex-end" wrap="nowrap">
                      <ActionIcon
                        variant="subtle"
                        aria-label={t('issues.search', { issue: issue.issueNumber })}
                        onClick={() => setSearching(issue)}
                      >
                        <IconSearch size={16} />
                      </ActionIcon>
                      <ActionIcon
                        variant="subtle"
                        aria-label={t('issues.editIssue', { issue: issue.issueNumber })}
                        onClick={() => setEditing(issue)}
                      >
                        <IconEdit size={16} />
                      </ActionIcon>
                      <ActionIcon
                        variant="subtle"
                        color="red"
                        aria-label={t('issues.deleteIssue', { issue: issue.issueNumber })}
                        onClick={() => setDeleting(issue)}
                      >
                        <IconTrash size={16} />
                      </ActionIcon>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}

      {editing && (
        <IssueModal key={editing.id} magazineId={magazineId} issue={editing} opened onClose={() => setEditing(null)} />
      )}
      <ConfirmModal
        opened={deleting !== null}
        title={t('issues.delete.title')}
        message={t('issues.delete.message', { issue: deleting?.issueNumber ?? '' })}
        confirmLabel={t('common.delete')}
        loading={remove.isPending}
        onClose={() => setDeleting(null)}
        onConfirm={() =>
          deleting && remove.mutate(deleting.id, { onSuccess: () => setDeleting(null), onError: notifyError })
        }
      />
      <SearchModal issue={searching} onClose={() => setSearching(null)} />
    </Stack>
  );
}
