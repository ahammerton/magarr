import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Group,
  List,
  Modal,
  MultiSelect,
  NumberInput,
  PasswordInput,
  SegmentedControl,
  Stack,
  Switch,
  Table,
  TagsInput,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { IconAlertTriangle, IconCheck, IconEdit, IconPlugConnected, IconPlus, IconRefresh, IconTrash } from '@tabler/icons-react';
import { useState } from 'react';

import {
  useDeleteIndexer,
  useIndexerCategories,
  useIndexers,
  useProwlarrConfig,
  useSaveIndexer,
  useSaveProwlarrConfig,
  useSyncProwlarr,
  useTestIndexerSettings,
  useTestProwlarr,
  useTestSavedIndexer,
  useToggleIndexer,
} from '../../api/indexers';
import type { Indexer, IndexerInput, ProwlarrConfig, SyncResult, TestResult } from '../../api/types';
import { ConfirmModal } from '../../components/ConfirmModal';
import { PageHeader } from '../../components/PageHeader';
import { QueryState } from '../../components/QueryState';
import { t } from '../../i18n';
import { notifyError, notifySuccess } from '../../notify';

function TestOutcome({ result }: { result: TestResult | undefined }) {
  if (!result) return null;
  return (
    <Alert
      color={result.ok ? 'teal' : 'red'}
      icon={result.ok ? <IconCheck /> : <IconAlertTriangle />}
      title={result.ok ? t('indexers.test.ok') : t('indexers.test.failed')}
    >
      {result.message}
    </Alert>
  );
}

function SyncSummary({ result }: { result: SyncResult }) {
  return (
    <Alert color="teal" icon={<IconCheck />} title={t('prowlarr.sync.done')}>
      <List size="sm">
        <List.Item>{t('prowlarr.sync.added', { names: result.added.join(', ') || '—' })}</List.Item>
        <List.Item>{t('prowlarr.sync.updated', { names: result.updated.join(', ') || '—' })}</List.Item>
        <List.Item>{t('prowlarr.sync.removed', { names: result.removed.join(', ') || '—' })}</List.Item>
        {result.skipped.map((s) => (
          <List.Item key={s.name}>{t('prowlarr.sync.skipped', { name: s.name, reason: s.reason })}</List.Item>
        ))}
      </List>
    </Alert>
  );
}

function ProwlarrForm({ initial }: { initial: ProwlarrConfig }) {
  const save = useSaveProwlarrConfig();
  const test = useTestProwlarr();
  const sync = useSyncProwlarr();
  const form = useForm({ initialValues: { url: initial.url, apiKey: initial.apiKey } });
  const configured = Boolean(initial.url && initial.apiKey);

  return (
    <Stack>
      <Group grow align="flex-start">
        <TextInput label={t('prowlarr.url')} placeholder="http://prowlarr:9696" {...form.getInputProps('url')} />
        <PasswordInput label={t('prowlarr.apiKey')} {...form.getInputProps('apiKey')} />
      </Group>
      <TestOutcome result={test.data} />
      {sync.data && <SyncSummary result={sync.data} />}
      <Group justify="space-between">
        <Text size="xs" c="dimmed">
          {initial.lastSync
            ? t('prowlarr.lastSync', { when: new Date(initial.lastSync).toLocaleString() })
            : t('prowlarr.neverSynced')}
        </Text>
        <Group gap="xs">
          <Button
            variant="default"
            leftSection={<IconPlugConnected size={16} />}
            loading={test.isPending}
            disabled={!form.values.url.trim()}
            onClick={() => test.mutate(form.values, { onError: notifyError })}
          >
            {t('common.test')}
          </Button>
          <Button
            variant="default"
            loading={save.isPending}
            disabled={!form.isDirty()}
            onClick={() =>
              save.mutate(form.values, {
                onSuccess: (saved) => {
                  const values = { url: saved.url, apiKey: saved.apiKey };
                  form.setValues(values);
                  form.resetDirty(values); // also clears per-field dirty flags
                  notifySuccess(t('prowlarr.saved'));
                },
                onError: notifyError,
              })
            }
          >
            {t('common.save')}
          </Button>
          <Button
            leftSection={<IconRefresh size={16} />}
            loading={sync.isPending}
            disabled={!configured || form.isDirty()}
            onClick={() => sync.mutate(undefined, { onError: notifyError })}
          >
            {t('prowlarr.sync')}
          </Button>
        </Group>
      </Group>
    </Stack>
  );
}

const EMPTY_INDEXER: IndexerInput = {
  name: '',
  implementation: 'newznab',
  baseUrl: '',
  apiPath: '/api',
  apiKey: '',
  categories: [7010],
  priority: 25,
  enabled: true,
  tags: [],
  requestInterval: 2,
};

function toInput(indexer: Indexer): IndexerInput {
  return {
    name: indexer.name,
    implementation: indexer.implementation,
    baseUrl: indexer.baseUrl,
    apiPath: indexer.apiPath,
    apiKey: indexer.apiKey,
    categories: indexer.categories,
    priority: indexer.priority,
    enabled: indexer.enabled,
    tags: indexer.tags,
    requestInterval: indexer.requestInterval,
  };
}

function IndexerModal({ indexer, onClose }: { indexer: Indexer | null; onClose: () => void }) {
  const save = useSaveIndexer();
  const test = useTestIndexerSettings();
  const categories = useIndexerCategories();
  const form = useForm<IndexerInput>({
    initialValues: indexer ? toInput(indexer) : EMPTY_INDEXER,
    validate: {
      name: (v) => (v.trim() ? null : t('indexers.validation.name')),
      baseUrl: (v) => (/^https?:\/\/.+/.test(v.trim()) ? null : t('indexers.validation.url')),
    },
  });
  const fromProwlarr = indexer?.source === 'prowlarr';

  // Offer every known category plus anything the indexer reported in its caps.
  const known = new Map<number, string>();
  for (const c of [...(categories.data ?? []), ...(test.data?.supportedCategories ?? []), ...(indexer?.supportedCategories ?? [])]) {
    known.set(c.id, `${c.id} · ${c.name}`);
  }
  const categoryOptions = [...known].sort((a, b) => a[0] - b[0]).map(([id, label]) => ({ value: String(id), label }));

  const submit = form.onSubmit((values) =>
    save.mutate(
      { id: indexer?.id, ...values },
      {
        onSuccess: () => {
          notifySuccess(t('indexers.saved'));
          onClose();
        },
        onError: notifyError,
      },
    ),
  );

  return (
    <Modal opened onClose={onClose} size="lg" title={indexer ? t('indexers.edit') : t('indexers.add')}>
      <form onSubmit={submit}>
        <Stack>
          {fromProwlarr && (
            <Alert color="blue">{t('indexers.fromProwlarr')}</Alert>
          )}
          <TextInput label={t('indexers.field.name')} withAsterisk data-autofocus {...form.getInputProps('name')} />
          <SegmentedControl
            disabled={fromProwlarr}
            data={[
              { value: 'newznab', label: t('indexers.newznab') },
              { value: 'torznab', label: t('indexers.torznab') },
            ]}
            {...form.getInputProps('implementation')}
          />
          <TextInput
            label={t('indexers.field.url')}
            withAsterisk
            placeholder="https://indexer.example"
            disabled={fromProwlarr}
            {...form.getInputProps('baseUrl')}
          />
          <Group grow align="flex-start">
            <TextInput label={t('indexers.field.apiPath')} disabled={fromProwlarr} {...form.getInputProps('apiPath')} />
            <PasswordInput label={t('indexers.field.apiKey')} disabled={fromProwlarr} {...form.getInputProps('apiKey')} />
          </Group>
          <MultiSelect
            label={t('indexers.field.categories')}
            description={t('indexers.field.categories.hint')}
            data={categoryOptions}
            value={form.values.categories.map(String)}
            onChange={(values) => form.setFieldValue('categories', values.map(Number))}
            searchable
          />
          <Group grow align="flex-start">
            <NumberInput
              label={t('indexers.field.priority')}
              description={t('indexers.field.priority.hint')}
              min={1}
              max={50}
              allowDecimal={false}
              {...form.getInputProps('priority')}
            />
            <NumberInput
              label={t('indexers.field.interval')}
              description={t('indexers.field.interval.hint')}
              min={0}
              max={60}
              decimalScale={1}
              {...form.getInputProps('requestInterval')}
            />
          </Group>
          <TagsInput
            label={t('indexers.field.tags')}
            description={t('indexers.field.tags.hint')}
            {...form.getInputProps('tags')}
          />
          <Switch label={t('indexers.field.enabled')} {...form.getInputProps('enabled', { type: 'checkbox' })} />
          <TestOutcome result={test.data} />
          <Group justify="space-between">
            <Button
              variant="default"
              leftSection={<IconPlugConnected size={16} />}
              loading={test.isPending}
              onClick={() => test.mutate({ id: indexer?.id, ...form.values }, { onError: notifyError })}
            >
              {t('common.test')}
            </Button>
            <Group gap="xs">
              <Button variant="default" onClick={onClose}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" loading={save.isPending}>
                {t('common.save')}
              </Button>
            </Group>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function HealthBadge({ indexer }: { indexer: Indexer }) {
  if (indexer.disabledUntil) {
    return (
      <Tooltip label={indexer.lastError ?? ''} multiline w={300}>
        <Badge color="red" variant="light">
          {t('indexers.status.backoff', { when: new Date(indexer.disabledUntil).toLocaleTimeString() })}
        </Badge>
      </Tooltip>
    );
  }
  if (indexer.consecutiveFailures > 0) {
    return (
      <Tooltip label={indexer.lastError ?? ''} multiline w={300}>
        <Badge color="orange" variant="light">
          {t('indexers.status.failing', { count: indexer.consecutiveFailures })}
        </Badge>
      </Tooltip>
    );
  }
  return (
    <Badge color={indexer.lastSuccess ? 'teal' : 'gray'} variant="light">
      {indexer.lastSuccess ? t('indexers.status.ok') : t('indexers.status.untested')}
    </Badge>
  );
}

function IndexerTable({ onEdit }: { onEdit: (indexer: Indexer) => void }) {
  const { data, isPending, error } = useIndexers();
  const toggle = useToggleIndexer();
  const test = useTestSavedIndexer();
  const remove = useDeleteIndexer();
  const [deleting, setDeleting] = useState<Indexer | null>(null);
  const [testing, setTesting] = useState<number | null>(null);

  const runTest = (indexer: Indexer) => {
    setTesting(indexer.id);
    test.mutate(indexer.id, {
      onSuccess: (result) =>
        result.ok ? notifySuccess(t('indexers.test.okNamed', { name: indexer.name })) : notifyError(new Error(result.message)),
      onError: notifyError,
      onSettled: () => setTesting(null),
    });
  };

  return (
    <QueryState isPending={isPending} error={error}>
      {() =>
        data!.length === 0 ? (
          <Text c="dimmed" size="sm">
            {t('indexers.empty')}
          </Text>
        ) : (
          <Table.ScrollContainer minWidth={760}>
            <Table verticalSpacing="xs">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('indexers.column.name')}</Table.Th>
                  <Table.Th>{t('indexers.column.protocol')}</Table.Th>
                  <Table.Th>{t('indexers.column.priority')}</Table.Th>
                  <Table.Th>{t('indexers.column.categories')}</Table.Th>
                  <Table.Th>{t('indexers.column.status')}</Table.Th>
                  <Table.Th>{t('indexers.column.enabled')}</Table.Th>
                  <Table.Th w={110} />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {data!.map((indexer) => (
                  <Table.Tr key={indexer.id} data-testid="indexer-row">
                    <Table.Td>
                      <Group gap={6}>
                        <Text size="sm" fw={500}>
                          {indexer.name}
                        </Text>
                        {indexer.source === 'prowlarr' && (
                          <Badge size="xs" variant="outline" color="orange">
                            Prowlarr
                          </Badge>
                        )}
                        {indexer.tags.map((tag) => (
                          <Badge key={tag} size="xs" variant="outline" color="gray">
                            {tag}
                          </Badge>
                        ))}
                      </Group>
                    </Table.Td>
                    <Table.Td>
                      <Badge variant="light" color={indexer.protocol === 'torrent' ? 'grape' : 'blue'}>
                        {t(`search.protocol.${indexer.protocol}`)}
                      </Badge>
                    </Table.Td>
                    <Table.Td>{indexer.priority}</Table.Td>
                    <Table.Td>
                      <Text size="xs">{indexer.categories.join(', ')}</Text>
                    </Table.Td>
                    <Table.Td>
                      <HealthBadge indexer={indexer} />
                    </Table.Td>
                    <Table.Td>
                      <Switch
                        aria-label={t('indexers.toggle', { name: indexer.name })}
                        checked={indexer.enabled}
                        onChange={(e) => toggle.mutate({ id: indexer.id, enabled: e.currentTarget.checked }, { onError: notifyError })}
                      />
                    </Table.Td>
                    <Table.Td>
                      <Group gap={2} justify="flex-end" wrap="nowrap">
                        <ActionIcon
                          variant="subtle"
                          aria-label={t('indexers.testNamed', { name: indexer.name })}
                          loading={testing === indexer.id}
                          onClick={() => runTest(indexer)}
                        >
                          <IconPlugConnected size={16} />
                        </ActionIcon>
                        <ActionIcon variant="subtle" aria-label={t('indexers.editNamed', { name: indexer.name })} onClick={() => onEdit(indexer)}>
                          <IconEdit size={16} />
                        </ActionIcon>
                        <ActionIcon
                          variant="subtle"
                          color="red"
                          aria-label={t('indexers.deleteNamed', { name: indexer.name })}
                          onClick={() => setDeleting(indexer)}
                        >
                          <IconTrash size={16} />
                        </ActionIcon>
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
            <ConfirmModal
              opened={deleting !== null}
              title={t('indexers.delete.title')}
              message={
                deleting?.source === 'prowlarr'
                  ? t('indexers.delete.prowlarr', { name: deleting.name })
                  : t('indexers.delete.message', { name: deleting?.name ?? '' })
              }
              confirmLabel={t('common.delete')}
              loading={remove.isPending}
              onClose={() => setDeleting(null)}
              onConfirm={() => deleting && remove.mutate(deleting.id, { onSuccess: () => setDeleting(null), onError: notifyError })}
            />
          </Table.ScrollContainer>
        )
      }
    </QueryState>
  );
}

export function IndexersPage() {
  const prowlarr = useProwlarrConfig();
  const [editing, setEditing] = useState<Indexer | 'new' | null>(null);

  return (
    <Stack gap="lg" maw={1100}>
      <PageHeader title={t('nav.settings.indexers')}>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setEditing('new')}>
          {t('indexers.add')}
        </Button>
      </PageHeader>
      <Card withBorder padding="lg">
        <Title order={4} mb="xs">
          {t('prowlarr.title')}
        </Title>
        <Text size="sm" c="dimmed" mb="md">
          {t('prowlarr.help')}
        </Text>
        <QueryState isPending={prowlarr.isPending} error={prowlarr.error}>
          {() => <ProwlarrForm initial={prowlarr.data!} />}
        </QueryState>
      </Card>
      <Card withBorder padding="lg">
        <Title order={4} mb="md">
          {t('indexers.title')}
        </Title>
        <IndexerTable onEdit={setEditing} />
      </Card>
      {editing && (
        <IndexerModal
          key={editing === 'new' ? 'new' : editing.id}
          indexer={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}
    </Stack>
  );
}

