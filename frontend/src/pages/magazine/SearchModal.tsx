import { Alert, Anchor, Badge, Button, Group, Modal, Stack, Table, Text, Tooltip, UnstyledButton } from '@mantine/core';
import {
  IconAlertTriangle,
  IconChevronDown,
  IconChevronUp,
  IconDownload,
  IconSelector,
} from '@tabler/icons-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { useGrab } from '../../api/downloads';
import { useIssueSearch } from '../../api/magazines';
import { useQualities } from '../../api/settings';
import type { Issue, Release } from '../../api/types';
import { ConfirmModal } from '../../components/ConfirmModal';
import { QueryState } from '../../components/QueryState';
import { formatBytes } from '../../format';
import { t, type MessageKey } from '../../i18n';
import { notifyError, notifySuccess } from '../../notify';

const NOWRAP = { whiteSpace: 'nowrap' } as const;
// Badges clip their label, so without this the table squeezes them to "TORRE…".
const FULL_BADGE = { minWidth: 'max-content' } as const;
// Scene names are dotted with no spaces; without this they can't wrap and the table overflows.
const BREAK_ANYWHERE = { overflowWrap: 'anywhere' } as const;

type SortKey = 'default' | 'title' | 'indexer' | 'age' | 'size' | 'peers';
interface Sort {
  key: SortKey;
  desc: boolean;
}

const COMPARE: Record<Exclude<SortKey, 'default'>, (a: Release, b: Release) => number> = {
  title: (a, b) => a.title.localeCompare(b.title),
  indexer: (a, b) => a.indexer.localeCompare(b.indexer),
  // Unknown age sorts as oldest.
  age: (a, b) => (a.ageDays ?? Number.MAX_SAFE_INTEGER) - (b.ageDays ?? Number.MAX_SAFE_INTEGER),
  size: (a, b) => a.size - b.size,
  peers: (a, b) => (a.seeders ?? -1) - (b.seeders ?? -1),
};

function SortHeader({
  label,
  column,
  sort,
  onSort,
  align,
}: {
  label: MessageKey;
  column: Exclude<SortKey, 'default'>;
  sort: Sort;
  onSort: (key: SortKey) => void;
  align?: 'right';
}) {
  const active = sort.key === column;
  const Icon = !active ? IconSelector : sort.desc ? IconChevronDown : IconChevronUp;
  return (
    <Table.Th ta={align} style={NOWRAP} aria-sort={active ? (sort.desc ? 'descending' : 'ascending') : 'none'}>
      <UnstyledButton onClick={() => onSort(column)} fw={700} fz="sm">
        <Group gap={4} wrap="nowrap" justify={align === 'right' ? 'flex-end' : 'flex-start'}>
          {t(label)}
          <Icon size={14} />
        </Group>
      </UnstyledButton>
    </Table.Th>
  );
}

function IndexerProblems({ outcomes }: { outcomes: NonNullable<ReturnType<typeof useIssueSearch>['data']>['indexers'] }) {
  const problems = outcomes.filter((o) => !o.ok);
  if (problems.length === 0) return null;
  return (
    <Alert color="orange" icon={<IconAlertTriangle />} title={t('search.indexerProblems')}>
      <Stack gap={2}>
        {problems.map((o) => (
          <Text size="sm" key={o.indexerId}>
            <b>{o.name}</b>:{' '}
            {o.skippedUntil
              ? t('search.skippedUntil', { when: new Date(o.skippedUntil).toLocaleTimeString(), error: o.error ?? '' })
              : o.error}
          </Text>
        ))}
      </Stack>
    </Alert>
  );
}

function GrabButton({
  release,
  issue,
  onForce,
}: {
  release: Release;
  issue: Issue;
  onForce: (release: Release) => void;
}) {
  const grab = useGrab();
  const [grabbed, setGrabbed] = useState(false);
  const run = () =>
    grab.mutate(
      { guid: release.guid, indexerId: release.indexerId, issueId: issue.id },
      {
        onSuccess: () => {
          setGrabbed(true);
          notifySuccess(t('search.grabbed', { title: release.title }));
        },
        onError: notifyError,
      },
    );
  if (grabbed) {
    return (
      <Badge color="teal" variant="light" style={{ minWidth: 'max-content' }}>
        {t('search.grabbedBadge')}
      </Badge>
    );
  }
  return (
    <Tooltip label={release.rejected ? t('search.grab.rejected') : t('search.grab.tooltip')}>
      <Button
        size="compact-sm"
        variant={release.rejected ? 'subtle' : 'light'}
        color={release.rejected ? 'gray' : undefined}
        loading={grab.isPending}
        leftSection={<IconDownload size={14} />}
        aria-label={t('search.grabNamed', { title: release.title })}
        onClick={() => (release.rejected ? onForce(release) : run())}
      >
        {t('search.grab')}
      </Button>
    </Tooltip>
  );
}

export function SearchModal({ issue, onClose }: { issue: Issue | null; onClose: () => void }) {
  const { data, isFetching, error } = useIssueSearch(issue?.id ?? null);
  const grab = useGrab();
  const [forcing, setForcing] = useState<Release | null>(null);
  const qualities = useQualities();
  const [sort, setSort] = useState<Sort>({ key: 'default', desc: false });
  const qualityName = (id: string) => qualities.data?.find((q) => q.id === id)?.name ?? id;

  const onSort = (key: SortKey) =>
    setSort((current) =>
      current.key === key
        ? { key, desc: !current.desc }
        : // Newest, biggest and best-seeded first is what people want on the first click.
          { key, desc: key === 'size' || key === 'peers' },
    );

  const releases = useMemo(() => {
    const list = [...(data?.releases ?? [])];
    if (sort.key !== 'default') {
      const compare = COMPARE[sort.key];
      list.sort((a, b) => (sort.desc ? -compare(a, b) : compare(a, b)));
    }
    return list;
  }, [data, sort]);

  return (
    <Modal
      opened={issue !== null}
      onClose={onClose}
      size="90rem"
      title={issue ? t('search.title', { issue: issue.issueNumber }) : ''}
    >
      {/* No data while closing (the query is switched off), so show nothing rather than crash. */}
      <QueryState isPending={(isFetching || !issue) && !data} error={error}>
        {() =>
          data ? (
          <Stack>
            {data.indexers.length === 0 && (
              <Alert color="blue" title={t('search.noIndexers.title')}>
                {t('search.noIndexers.body')}{' '}
                <Anchor component={Link} to="/settings/indexers" onClick={onClose}>
                  {t('nav.settings.indexers')}
                </Anchor>
              </Alert>
            )}
            <IndexerProblems outcomes={data.indexers} />
            {data.queries.length > 0 && (
              <Text size="xs" c="dimmed">
                {t('search.summary', {
                  count: data.releases.length,
                  approved: data.releases.filter((r) => !r.rejected).length,
                  queries: data.queries.map((q) => `“${q}”`).join(', '),
                })}
              </Text>
            )}
            {releases.length > 0 && (
              <Table.ScrollContainer minWidth={900}>
                <Table verticalSpacing="xs" striped>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>{t('search.column.protocol')}</Table.Th>
                      <SortHeader label="search.column.title" column="title" sort={sort} onSort={onSort} />
                      <Table.Th>{t('search.column.issue')}</Table.Th>
                      <Table.Th>{t('search.column.quality')}</Table.Th>
                      <SortHeader label="search.column.indexer" column="indexer" sort={sort} onSort={onSort} />
                      <SortHeader label="search.column.age" column="age" sort={sort} onSort={onSort} align="right" />
                      <SortHeader label="search.column.size" column="size" sort={sort} onSort={onSort} align="right" />
                      <SortHeader label="search.column.peers" column="peers" sort={sort} onSort={onSort} align="right" />
                      <Table.Th />
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {releases.map((release) => (
                      <Table.Tr key={`${release.indexerId}-${release.guid}`} opacity={release.rejected ? 0.6 : 1} data-testid="release-row">
                        <Table.Td style={NOWRAP}>
                          <Badge variant="light" color={release.protocol === 'torrent' ? 'grape' : 'blue'} style={FULL_BADGE}>
                            {t(`search.protocol.${release.protocol}`)}
                          </Badge>
                        </Table.Td>
                        <Table.Td>
                          <Group gap={6} wrap="nowrap">
                            {release.rejected && (
                              <Tooltip label={release.rejectionReasons.join('\n')} multiline w={300}>
                                <IconAlertTriangle
                                  size={16}
                                  color="var(--mantine-color-red-5)"
                                  aria-label={release.rejectionReasons.join('; ')}
                                />
                              </Tooltip>
                            )}
                            {release.infoUrl ? (
                              <Anchor
                                href={release.infoUrl}
                                target="_blank"
                                rel="noreferrer"
                                size="sm"
                                ff="monospace"
                                style={BREAK_ANYWHERE}
                              >
                                {release.title}
                              </Anchor>
                            ) : (
                              <Text size="sm" ff="monospace" style={BREAK_ANYWHERE}>
                                {release.title}
                              </Text>
                            )}
                          </Group>
                        </Table.Td>
                        <Table.Td style={NOWRAP}>{release.parsed.issueNumber ?? '—'}</Table.Td>
                        <Table.Td style={NOWRAP}>
                          <Badge variant="outline" size="sm" color="gray" style={FULL_BADGE}>
                            {qualityName(release.parsed.quality)}
                          </Badge>
                        </Table.Td>
                        <Table.Td>{release.indexer}</Table.Td>
                        <Table.Td ta="right" style={NOWRAP}>
                          {release.ageDays === null ? '—' : t('search.ageDays', { days: release.ageDays })}
                        </Table.Td>
                        <Table.Td ta="right" style={NOWRAP}>
                          {formatBytes(release.size)}
                        </Table.Td>
                        <Table.Td ta="right" style={NOWRAP}>
                          {release.seeders === null ? '—' : `${release.seeders}/${release.leechers ?? 0}`}
                        </Table.Td>
                        <Table.Td>
                          <GrabButton release={release} issue={issue!} onForce={setForcing} />
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Table.ScrollContainer>
            )}
            {data.indexers.length > 0 && releases.length === 0 && <Text c="dimmed">{t('search.noResults')}</Text>}
          </Stack>
          ) : null
        }
      </QueryState>
      <ConfirmModal
        opened={forcing !== null}
        title={t('search.force.title')}
        message={t('search.force.message', { reasons: forcing?.rejectionReasons.join('; ') ?? '' })}
        confirmLabel={t('search.force.confirm')}
        loading={grab.isPending}
        onClose={() => setForcing(null)}
        onConfirm={() =>
          forcing &&
          issue &&
          grab.mutate(
            { guid: forcing.guid, indexerId: forcing.indexerId, issueId: issue.id },
            {
              onSuccess: () => {
                notifySuccess(t('search.grabbed', { title: forcing.title }));
                setForcing(null);
              },
              onError: notifyError,
            },
          )
        }
      />
    </Modal>
  );
}
