import {
  ActionIcon,
  Anchor,
  Badge,
  Button,
  Card,
  Center,
  Checkbox,
  Group,
  Menu,
  Modal,
  MultiSelect,
  Paper,
  Progress,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  ThemeIcon,
} from '@mantine/core';
import {
  IconBookmark,
  IconBookmarkOff,
  IconFilter,
  IconGripVertical,
  IconInbox,
  IconLayoutGrid,
  IconList,
  IconPlus,
  IconRefresh,
  IconSearch,
  IconTrash,
} from '@tabler/icons-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { useDeleteMagazines, useMagazineEditor, useMagazines, type MagazineEditorChanges } from '../../api/magazines';
import { useLibraryScan, useQualityProfiles, useRootFolders } from '../../api/settings';
import type { Frequency, Magazine } from '../../api/types';
import { ConfirmModal } from '../../components/ConfirmModal';
import { FREQUENCIES } from '../../components/magazineForm';
import { PageHeader } from '../../components/PageHeader';
import { Poster } from '../../components/Poster';
import { QueryState } from '../../components/QueryState';
import { formatBytes } from '../../format';
import { t } from '../../i18n';
import { notifyError, notifySuccess } from '../../notify';
import { applies, filterLabel, PRESETS, reorder, sortMagazines, stored, type LibraryFilter, type SortKey } from './libraryView';

type View = 'grid' | 'table';
const VIEW_KEY = 'magarr.library.view';
const SORTS: SortKey[] = ['title', 'added', 'size', 'wanted', 'custom'];

function loadView(): View {
  try {
    return localStorage.getItem(VIEW_KEY) === 'table' ? 'table' : 'grid';
  } catch {
    return 'grid';
  }
}

function saveView(view: View): void {
  try {
    localStorage.setItem(VIEW_KEY, view);
  } catch {
    // Storage unavailable; the choice just won't persist.
  }
}

function matches(magazine: Magazine, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [magazine.title, ...magazine.alternateTitles, magazine.publisher ?? '', ...magazine.tags]
    .some((text) => text.toLowerCase().includes(q));
}

function IssueProgress({ magazine }: { magazine: Magazine }) {
  const { issueCount, downloadedCount } = magazine.statistics;
  const percent = issueCount ? (downloadedCount / issueCount) * 100 : 0;
  return (
    <Progress
      value={percent}
      size="sm"
      color={percent === 100 ? 'teal' : 'violet'}
      aria-label={t('library.progress', { downloaded: downloadedCount, total: issueCount })}
    />
  );
}

function MagazineGrid({
  magazines,
  onReorder,
}: {
  magazines: Magazine[];
  /** Set when the custom order is shown: posters can then be dragged into place. */
  onReorder?: (moved: number, target: number) => void;
}) {
  const [dragging, setDragging] = useState<number | null>(null);
  const [over, setOver] = useState<number | null>(null);
  return (
    <SimpleGrid cols={{ base: 2, xs: 3, sm: 4, md: 5, lg: 7 }} spacing="md">
      {magazines.map((magazine) => {
        const { issueCount, downloadedCount } = magazine.statistics;
        const drag = onReorder
          ? {
              draggable: true,
              onDragStart: (e: React.DragEvent) => {
                e.dataTransfer.effectAllowed = 'move';
                setDragging(magazine.id);
              },
              onDragOver: (e: React.DragEvent) => {
                e.preventDefault();
                setOver(magazine.id);
              },
              onDragEnd: () => {
                setDragging(null);
                setOver(null);
              },
              onDrop: (e: React.DragEvent) => {
                e.preventDefault();
                if (dragging !== null && dragging !== magazine.id) onReorder(dragging, magazine.id);
                setDragging(null);
                setOver(null);
              },
            }
          : {};
        return (
          <Card
            key={magazine.id}
            component={Link}
            to={`/magazine/${magazine.id}`}
            padding="xs"
            withBorder
            data-testid="magazine-card"
            opacity={dragging === magazine.id ? 0.4 : 1}
            style={over === magazine.id && dragging !== magazine.id ? { outline: '2px solid var(--mantine-primary-color-filled)' } : undefined}
            {...drag}
          >
            <Card.Section pos="relative">
              <Poster title={magazine.title} url={magazine.posterUrl} coverUrl={magazine.coverUrl} />
              {onReorder && (
                <ThemeIcon size="sm" variant="filled" color="dark" pos="absolute" top={6} right={6} opacity={0.7} aria-hidden>
                  <IconGripVertical size={14} />
                </ThemeIcon>
              )}
            </Card.Section>
            <Stack gap={4} mt="xs">
              <Text fw={600} size="sm" lineClamp={2}>
                {magazine.title}
              </Text>
              <IssueProgress magazine={magazine} />
              <Group justify="space-between" gap={4}>
                <Text size="xs" c="dimmed">
                  {downloadedCount}/{issueCount}
                </Text>
                {!magazine.monitored && (
                  <Badge size="xs" color="gray" variant="light">
                    {t('library.unmonitored')}
                  </Badge>
                )}
              </Group>
            </Stack>
          </Card>
        );
      })}
    </SimpleGrid>
  );
}

function BulkToolbar({ ids, onDone }: { ids: number[]; onDone: () => void }) {
  const edit = useMagazineEditor();
  const remove = useDeleteMagazines();
  const profiles = useQualityProfiles();
  const roots = useRootFolders();
  const [deleting, setDeleting] = useState(false);
  const apply = (changes: MagazineEditorChanges) =>
    edit.mutate(
      { ids, ...changes },
      {
        onSuccess: (updated) => {
          notifySuccess(t('library.bulk.saved', { count: updated.length }));
          onDone();
        },
        onError: notifyError,
      },
    );
  return (
    <Paper withBorder p="xs" data-testid="bulk-toolbar">
      <Group gap="xs">
        <Text size="sm" fw={500}>
          {t('library.bulk.selected', { count: ids.length })}
        </Text>
        <Button size="xs" variant="default" leftSection={<IconBookmark size={14} />} loading={edit.isPending} onClick={() => apply({ monitored: true })}>
          {t('library.bulk.monitor')}
        </Button>
        <Button size="xs" variant="default" leftSection={<IconBookmarkOff size={14} />} loading={edit.isPending} onClick={() => apply({ monitored: false })}>
          {t('library.bulk.unmonitor')}
        </Button>
        <Select
          size="xs"
          w={170}
          placeholder={t('library.bulk.profile')}
          aria-label={t('library.bulk.profile')}
          data={(profiles.data ?? []).map((p) => ({ value: String(p.id), label: p.name }))}
          value={null}
          onChange={(v) => v && apply({ qualityProfileId: Number(v) })}
        />
        <Select
          size="xs"
          w={200}
          placeholder={t('library.bulk.rootFolder')}
          aria-label={t('library.bulk.rootFolder')}
          data={(roots.data ?? []).map((r) => ({ value: String(r.id), label: r.path }))}
          value={null}
          onChange={(v) => v && apply({ rootFolderId: Number(v) })}
        />
        <Menu>
          <Menu.Target>
            <Button size="xs" variant="default">
              {t('magazine.field.grabNewSpecials')}
            </Button>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item onClick={() => apply({ grabNewSpecials: true })}>{t('library.bulk.on')}</Menu.Item>
            <Menu.Item onClick={() => apply({ grabNewSpecials: false })}>{t('library.bulk.off')}</Menu.Item>
          </Menu.Dropdown>
        </Menu>
        <Button size="xs" color="red" variant="light" leftSection={<IconTrash size={14} />} onClick={() => setDeleting(true)}>
          {t('common.delete')}
        </Button>
      </Group>
      <ConfirmModal
        opened={deleting}
        title={t('library.bulk.delete.title', { count: ids.length })}
        message={t('library.bulk.delete.message')}
        confirmLabel={t('common.delete')}
        loading={remove.isPending}
        onClose={() => setDeleting(false)}
        onConfirm={() =>
          remove.mutate(ids, {
            onSuccess: () => {
              setDeleting(false);
              onDone();
            },
            onError: notifyError,
          })
        }
      />
    </Paper>
  );
}

function MagazineTable({ magazines }: { magazines: Magazine[] }) {
  const profiles = useQualityProfiles();
  const profileName = (id: number) => profiles.data?.find((p) => p.id === id)?.name ?? '';
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const chosen = magazines.filter((m) => selected.has(m.id)).map((m) => m.id);
  const allSelected = magazines.length > 0 && chosen.length === magazines.length;
  const toggle = (id: number) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  return (
    <Stack gap="sm">
      {chosen.length > 0 && <BulkToolbar ids={chosen} onDone={() => setSelected(new Set())} />}
      <Table.ScrollContainer minWidth={680}>
        <Table highlightOnHover verticalSpacing="xs">
          <Table.Thead>
            <Table.Tr>
              <Table.Th w={36}>
                <Checkbox
                  aria-label={t('library.selectAll')}
                  checked={allSelected}
                  indeterminate={chosen.length > 0 && !allSelected}
                  onChange={() => setSelected(allSelected ? new Set() : new Set(magazines.map((m) => m.id)))}
                />
              </Table.Th>
              <Table.Th w={32} />
              <Table.Th>{t('library.column.title')}</Table.Th>
              <Table.Th>{t('library.column.frequency')}</Table.Th>
              <Table.Th>{t('library.column.issues')}</Table.Th>
              <Table.Th>{t('library.column.wanted')}</Table.Th>
              <Table.Th>{t('library.column.profile')}</Table.Th>
              <Table.Th ta="right">{t('library.column.size')}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {magazines.map((magazine) => (
              <Table.Tr key={magazine.id} data-testid="magazine-row">
                <Table.Td>
                  <Checkbox
                    aria-label={t('library.select', { title: magazine.title })}
                    checked={selected.has(magazine.id)}
                    onChange={() => toggle(magazine.id)}
                  />
                </Table.Td>
                <Table.Td>
                  {magazine.monitored ? (
                    <IconBookmark size={16} aria-label={t('common.monitored')} />
                  ) : (
                    <IconBookmarkOff size={16} aria-label={t('common.unmonitored')} opacity={0.5} />
                  )}
                </Table.Td>
                <Table.Td>
                  <Anchor component={Link} to={`/magazine/${magazine.id}`} fw={500}>
                    {magazine.title}
                  </Anchor>
                </Table.Td>
                <Table.Td>{t(`frequency.${magazine.frequency}`)}</Table.Td>
                <Table.Td w={160}>
                  <Stack gap={2}>
                    <IssueProgress magazine={magazine} />
                    <Text size="xs" c="dimmed">
                      {magazine.statistics.downloadedCount}/{magazine.statistics.issueCount}
                    </Text>
                  </Stack>
                </Table.Td>
                <Table.Td>{magazine.statistics.wantedCount}</Table.Td>
                <Table.Td>{profileName(magazine.qualityProfileId)}</Table.Td>
                <Table.Td ta="right">{formatBytes(magazine.statistics.sizeOnDisk)}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Stack>
  );
}

type Tri = 'any' | 'yes' | 'no';
const tri = (value: Tri): boolean | undefined => (value === 'any' ? undefined : value === 'yes');

function FilterModal({ onSave, onClose }: { onSave: (filter: LibraryFilter) => void; onClose: () => void }) {
  const [name, setName] = useState('');
  const [monitored, setMonitored] = useState<Tri>('any');
  const [hasWanted, setHasWanted] = useState<Tri>('any');
  const [complete, setComplete] = useState<Tri>('any');
  const [frequencies, setFrequencies] = useState<Frequency[]>([]);
  const [category, setCategory] = useState('');
  const [tag, setTag] = useState('');
  const triData = (['any', 'yes', 'no'] as const).map((v) => ({ value: v, label: t(`library.filter.${v}`) }));
  return (
    <Modal opened onClose={onClose} title={t('library.filter.new')}>
      <Stack>
        <TextInput label={t('library.filter.name')} withAsterisk value={name} onChange={(e) => setName(e.currentTarget.value)} data-autofocus />
        <Group grow>
          <Select label={t('library.filter.monitored')} data={triData} value={monitored} allowDeselect={false} onChange={(v) => setMonitored(v as Tri)} />
          <Select label={t('library.filter.hasWanted')} data={triData} value={hasWanted} allowDeselect={false} onChange={(v) => setHasWanted(v as Tri)} />
          <Select label={t('library.filter.complete')} data={triData} value={complete} allowDeselect={false} onChange={(v) => setComplete(v as Tri)} />
        </Group>
        <MultiSelect
          label={t('library.filter.frequency')}
          placeholder={t('library.filter.anyFrequency')}
          data={FREQUENCIES.map((f) => ({ value: f, label: t(`frequency.${f}`) }))}
          value={frequencies}
          onChange={(v) => setFrequencies(v as Frequency[])}
        />
        <Group grow>
          <TextInput label={t('library.filter.category')} value={category} onChange={(e) => setCategory(e.currentTarget.value)} />
          <TextInput label={t('library.filter.tag')} value={tag} onChange={(e) => setTag(e.currentTarget.value)} />
        </Group>
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            disabled={!name.trim()}
            onClick={() =>
              onSave({
                id: `custom-${Date.now()}`,
                name: name.trim(),
                monitored: tri(monitored),
                hasWanted: tri(hasWanted),
                complete: tri(complete),
                frequencies: frequencies.length ? frequencies : undefined,
                category: category.trim() || undefined,
                tag: tag.trim() || undefined,
              })
            }
          >
            {t('common.save')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function EmptyLibrary() {
  return (
    <Center py={80}>
      <Stack align="center" gap="xs">
        <ThemeIcon variant="light" size={56} radius="xl">
          <IconInbox size={30} stroke={1.5} />
        </ThemeIcon>
        <Text fw={600}>{t('library.empty.title')}</Text>
        <Text c="dimmed" size="sm">
          {t('library.empty.description')}
        </Text>
        <Button component={Link} to="/library/add" leftSection={<IconPlus size={16} />} mt="sm">
          {t('library.add')}
        </Button>
      </Stack>
    </Center>
  );
}

export function MagazineIndexPage() {
  const { data, isPending, error } = useMagazines();
  const scan = useLibraryScan();
  const [view, setView] = useState<View>(loadView);
  const [query, setQuery] = useState('');
  const [saved, setSaved] = useState<LibraryFilter[]>(stored.filters);
  const [filterId, setFilterId] = useState('all');
  const [creating, setCreating] = useState(false);
  const [sort, setSort] = useState<SortKey>(stored.sort);
  const [order, setOrder] = useState<number[]>(stored.order);
  const filters = useMemo(() => [...PRESETS, ...saved], [saved]);
  const filter = filters.find((f) => f.id === filterId) ?? PRESETS[0]!;
  const visible = useMemo(
    () => sortMagazines((data ?? []).filter((m) => matches(m, query) && applies(filter, m)), sort, order),
    [data, query, filter, sort, order],
  );

  const runScan = () =>
    scan.mutate(undefined, {
      onSuccess: (results) => {
        const added = results.reduce((sum, r) => sum + r.filesAdded, 0);
        const unmapped = results.reduce((sum, r) => sum + r.unmapped, 0);
        const created = results.reduce((sum, r) => sum + r.magazinesCreated, 0);
        notifySuccess(
          created
            ? t('library.scan.doneCreated', { created, added, unmapped })
            : t('library.scan.done', { added, unmapped }),
        );
      },
      onError: notifyError,
    });

  const saveFilter = (created: LibraryFilter) => {
    const next = [...saved, created];
    setSaved(next);
    stored.saveFilters(next);
    setFilterId(created.id);
    setCreating(false);
  };
  const deleteFilter = (id: string) => {
    const next = saved.filter((f) => f.id !== id);
    setSaved(next);
    stored.saveFilters(next);
    if (filterId === id) setFilterId('all');
  };
  const moveTo = (moved: number, target: number) => {
    const next = reorder(visible.map((m) => m.id), moved, target);
    // Keep the places of magazines hidden by the search or filter.
    const merged = [...next, ...order.filter((id) => !next.includes(id))];
    setOrder(merged);
    stored.saveOrder(merged);
  };

  return (
    <Stack gap="lg">
      <PageHeader title={t('library.title')}>
        <TextInput
          placeholder={t('library.search')}
          aria-label={t('library.search')}
          leftSection={<IconSearch size={16} />}
          value={query}
          onChange={(event) => setQuery(event.currentTarget.value)}
          w={220}
          data-shortcut-search
        />
        <Menu position="bottom-end" width={240}>
          <Menu.Target>
            <Button variant={filterId === 'all' ? 'default' : 'light'} leftSection={<IconFilter size={16} />}>
              {filterLabel(filter)}
            </Button>
          </Menu.Target>
          <Menu.Dropdown>
            {PRESETS.map((p) => (
              <Menu.Item key={p.id} onClick={() => setFilterId(p.id)} fw={p.id === filterId ? 700 : undefined}>
                {filterLabel(p)}
              </Menu.Item>
            ))}
            {saved.length > 0 && <Menu.Divider />}
            {saved.map((f) => (
              <Menu.Item
                key={f.id}
                onClick={() => setFilterId(f.id)}
                fw={f.id === filterId ? 700 : undefined}
                rightSection={
                  <ActionIcon
                    size="xs"
                    variant="subtle"
                    color="red"
                    aria-label={t('library.filter.delete', { name: f.name })}
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteFilter(f.id);
                    }}
                  >
                    <IconTrash size={12} />
                  </ActionIcon>
                }
              >
                {f.name}
              </Menu.Item>
            ))}
            <Menu.Divider />
            <Menu.Item leftSection={<IconPlus size={14} />} onClick={() => setCreating(true)}>
              {t('library.filter.new')}
            </Menu.Item>
          </Menu.Dropdown>
        </Menu>
        <Select
          aria-label={t('library.sort')}
          w={150}
          data={SORTS.map((s) => ({ value: s, label: t(`library.sort.${s}`) }))}
          value={sort}
          allowDeselect={false}
          onChange={(value) => {
            setSort(value as SortKey);
            stored.saveSort(value as SortKey);
          }}
        />
        <SegmentedControl
          value={view}
          onChange={(value) => {
            setView(value as View);
            saveView(value as View);
          }}
          data={[
            { value: 'grid', label: <IconLayoutGrid size={16} aria-label={t('library.view.grid')} /> },
            { value: 'table', label: <IconList size={16} aria-label={t('library.view.table')} /> },
          ]}
        />
        <Button
          variant="default"
          leftSection={<IconRefresh size={16} />}
          loading={scan.isPending}
          onClick={runScan}
        >
          {t('library.scan')}
        </Button>
        <Button component={Link} to="/library/add" leftSection={<IconPlus size={16} />}>
          {t('library.add')}
        </Button>
      </PageHeader>
      {sort === 'custom' && view === 'grid' && (
        <Text size="xs" c="dimmed">
          {t('library.sort.custom.hint')}
        </Text>
      )}
      <QueryState isPending={isPending} error={error}>
        {() =>
          data!.length === 0 ? (
            <EmptyLibrary />
          ) : visible.length === 0 ? (
            <Text c="dimmed">{t('library.noMatches')}</Text>
          ) : view === 'grid' ? (
            <MagazineGrid magazines={visible} onReorder={sort === 'custom' ? moveTo : undefined} />
          ) : (
            <MagazineTable magazines={visible} />
          )
        }
      </QueryState>
      {creating && <FilterModal onSave={saveFilter} onClose={() => setCreating(false)} />}
    </Stack>
  );
}
