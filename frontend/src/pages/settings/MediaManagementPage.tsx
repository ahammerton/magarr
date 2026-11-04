import {
  ActionIcon,
  NumberInput,
  Select,
  Alert,
  Badge,
  Button,
  Card,
  Code,
  Group,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core';
import { useForm } from '@mantine/form';
import { useDebouncedValue } from '@mantine/hooks';
import { IconAlertTriangle, IconStar, IconTrash } from '@tabler/icons-react';
import { useEffect, useState } from 'react';

import {
  useAddRootFolder,
  useDeleteRootFolder,
  useNamingConfig,
  useNamingPreview,
  useRootFolders,
  useSaveNamingConfig,
  useSetDefaultRootFolder,
} from '../../api/settings';
import { useMediaSettings, useSaveMediaSettings } from '../../api/media';
import type { MediaSettings, NamingConfig } from '../../api/types';
import { PageHeader } from '../../components/PageHeader';
import { QueryState } from '../../components/QueryState';
import { formatBytes } from '../../format';
import { t } from '../../i18n';
import { notifyError, notifySuccess } from '../../notify';

const MONO = { input: { fontFamily: 'var(--mantine-font-family-monospace)' } };

function RootFolders() {
  const { data, isPending, error } = useRootFolders();
  const add = useAddRootFolder();
  const setDefault = useSetDefaultRootFolder();
  const remove = useDeleteRootFolder();
  const [path, setPath] = useState('');

  const submit = () =>
    add.mutate(path, {
      onSuccess: () => {
        setPath('');
        notifySuccess(t('rootFolders.added'));
      },
      onError: notifyError,
    });

  return (
    <Card withBorder padding="lg">
      <Title order={4} mb="xs">
        {t('rootFolders.title')}
      </Title>
      <Text size="sm" c="dimmed" mb="md">
        {t('rootFolders.help')}
      </Text>
      <QueryState isPending={isPending} error={error}>
        {() =>
          data!.length > 0 && (
            <Table mb="md" verticalSpacing="xs">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('rootFolders.column.path')}</Table.Th>
                  <Table.Th ta="right" style={{ whiteSpace: 'nowrap' }}>
                    {t('rootFolders.column.free')}
                  </Table.Th>
                  <Table.Th w={90} />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {data!.map((root) => (
                  <Table.Tr key={root.id}>
                    <Table.Td>
                      <Group gap="xs">
                        <Code>{root.path}</Code>
                        {root.isDefault && <Badge size="sm">{t('rootFolders.default')}</Badge>}
                        {!root.accessible && (
                          <Tooltip label={t('rootFolders.inaccessible')}>
                            <IconAlertTriangle size={16} color="var(--mantine-color-orange-5)" aria-label={t('rootFolders.inaccessible')} />
                          </Tooltip>
                        )}
                      </Group>
                    </Table.Td>
                    <Table.Td ta="right">{root.freeSpace === null ? '—' : formatBytes(root.freeSpace)}</Table.Td>
                    <Table.Td>
                      <Group gap={2} justify="flex-end">
                        {!root.isDefault && (
                          <ActionIcon
                            variant="subtle"
                            aria-label={t('rootFolders.makeDefault', { path: root.path })}
                            onClick={() => setDefault.mutate(root.id, { onError: notifyError })}
                          >
                            <IconStar size={16} />
                          </ActionIcon>
                        )}
                        <ActionIcon
                          variant="subtle"
                          color="red"
                          aria-label={t('rootFolders.remove', { path: root.path })}
                          onClick={() => remove.mutate(root.id, { onError: notifyError })}
                        >
                          <IconTrash size={16} />
                        </ActionIcon>
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )
        }
      </QueryState>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (path.trim()) submit();
        }}
      >
        <Group align="flex-end">
          <TextInput
            label={t('rootFolders.add.label')}
            placeholder="/magazines"
            value={path}
            onChange={(event) => setPath(event.currentTarget.value)}
            style={{ flex: 1 }}
          />
          <Button type="submit" loading={add.isPending} disabled={!path.trim()}>
            {t('rootFolders.add')}
          </Button>
        </Group>
      </form>
    </Card>
  );
}

function NamingForm({ initial }: { initial: NamingConfig }) {
  const save = useSaveNamingConfig();
  const preview = useNamingPreview();
  const form = useForm<NamingConfig>({ initialValues: initial });
  const [debounced] = useDebouncedValue(form.values, 300);
  const { mutate: requestPreview } = preview;

  useEffect(() => {
    requestPreview(debounced);
  }, [debounced, requestPreview]);

  const submit = form.onSubmit((values) =>
    save.mutate(values, {
      onSuccess: (saved) => {
        form.resetDirty(saved);
        notifySuccess(t('naming.saved'));
      },
      onError: notifyError,
    }),
  );

  return (
    <form onSubmit={submit}>
      <Stack>
        <TextInput label={t('naming.magazineFolder')} styles={MONO} {...form.getInputProps('magazineFolderPattern')} />
        <TextInput
          label={t('naming.yearFolder')}
          description={t('naming.yearFolder.hint')}
          styles={MONO}
          {...form.getInputProps('yearFolderPattern')}
        />
        <TextInput label={t('naming.issueFile')} styles={MONO} {...form.getInputProps('issueFilePattern')} />
        <Switch
          label={t('naming.replaceIllegal')}
          description={t('naming.replaceIllegal.hint')}
          {...form.getInputProps('replaceIllegalCharacters', { type: 'checkbox' })}
        />
        <TextInput
          label={t('naming.colon')}
          description={t('naming.colon.hint')}
          maxLength={8}
          w={200}
          {...form.getInputProps('colonReplacement')}
        />

        {preview.error ? (
          <Alert color="red" icon={<IconAlertTriangle />}>
            {preview.error.message}
          </Alert>
        ) : (
          preview.data && (
            <Card withBorder bg="var(--mantine-color-dark-7)">
              <Text size="xs" c="dimmed" tt="uppercase" fw={600} mb={4}>
                {t('naming.preview')}
              </Text>
              <Code block>{preview.data.issuePath}</Code>
              <Text size="xs" c="dimmed" mt="sm">
                {t('naming.tokens')} {preview.data.tokens.issueFile.map((tok) => `{${tok}}`).join(' ')}
              </Text>
            </Card>
          )
        )}
        <Group justify="flex-end">
          <Button type="submit" loading={save.isPending} disabled={!form.isDirty()}>
            {t('common.save')}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

function ImportingCard() {
  const settings = useMediaSettings();
  const save = useSaveMediaSettings();
  return (
    <Card withBorder padding="lg">
      <Title order={4} mb="xs">
        {t('importing.title')}
      </Title>
      <Text size="sm" c="dimmed" mb="md">
        {t('importing.help')}
      </Text>
      <QueryState isPending={settings.isPending} error={settings.error}>
        {() => <ImportingForm initial={settings.data!} onSave={(values) => save.mutate(values, { onSuccess: () => notifySuccess(t('importing.saved')), onError: notifyError })} saving={save.isPending} />}
      </QueryState>
    </Card>
  );
}

function ImportingForm({ initial, onSave, saving }: { initial: MediaSettings; onSave: (v: MediaSettings) => void; saving: boolean }) {
  const form = useForm<MediaSettings>({ initialValues: initial });
  const modes = (['move', 'copy', 'hardlink'] as const).map((m) => ({ value: m, label: t(`importing.mode.${m}`) }));
  return (
    <form
      onSubmit={form.onSubmit((values) => {
        onSave(values);
        form.resetDirty(values);
      })}
    >
      <Stack>
        <Switch label={t('importing.auto')} description={t('importing.auto.hint')} {...form.getInputProps('autoImport', { type: 'checkbox' })} />
        <Group grow align="flex-start">
          <Select label={t('importing.usenetMode')} data={modes} allowDeselect={false} {...form.getInputProps('usenetImportMode')} />
          <Select label={t('importing.torrentMode')} description={t('importing.torrentMode.hint')} data={modes} allowDeselect={false} {...form.getInputProps('torrentImportMode')} />
        </Group>
        <Switch label={t('importing.removeCompleted')} description={t('importing.removeCompleted.hint')} {...form.getInputProps('removeCompletedDownloads', { type: 'checkbox' })} />
        <TextInput label={t('importing.recycleBin')} description={t('importing.recycleBin.hint')} placeholder="/magazines/.recycle" styles={MONO} {...form.getInputProps('recycleBin')} />
        <Group grow align="flex-start">
          <TextInput label={t('importing.fileChmod')} placeholder="664" maxLength={4} {...form.getInputProps('fileChmod')} />
          <TextInput label={t('importing.folderChmod')} placeholder="775" maxLength={4} {...form.getInputProps('folderChmod')} />
          <NumberInput label={t('importing.chownUser')} placeholder="—" min={0} allowDecimal={false} value={form.values.chownUser ?? ''} onChange={(v) => form.setFieldValue('chownUser', v === '' ? null : Number(v))} />
          <NumberInput label={t('importing.chownGroup')} placeholder="—" min={0} allowDecimal={false} value={form.values.chownGroup ?? ''} onChange={(v) => form.setFieldValue('chownGroup', v === '' ? null : Number(v))} />
        </Group>
        <Text size="xs" c="dimmed">
          {t('importing.permissions.hint')}
        </Text>
        <Group justify="flex-end">
          <Button type="submit" loading={saving} disabled={!form.isDirty()}>
            {t('common.save')}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

export function MediaManagementPage() {
  const naming = useNamingConfig();
  return (
    <Stack gap="lg" maw={900}>
      <PageHeader title={t('nav.settings.media')} />
      <RootFolders />
      <ImportingCard />
      <Card withBorder padding="lg">
        <Title order={4} mb="xs">
          {t('naming.title')}
        </Title>
        <Text size="sm" c="dimmed" mb="md">
          {t('naming.help')}
        </Text>
        <QueryState isPending={naming.isPending} error={naming.error}>
          {() => <NamingForm initial={naming.data!} />}
        </QueryState>
      </Card>
    </Stack>
  );
}
