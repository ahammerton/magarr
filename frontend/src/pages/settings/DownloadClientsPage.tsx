import {
  ActionIcon,
  Autocomplete,
  Badge,
  Button,
  Card,
  Group,
  Modal,
  NumberInput,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { IconEdit, IconPlugConnected, IconPlus, IconTrash } from '@tabler/icons-react';
import { useState } from 'react';

import {
  useDeleteDownloadClient,
  useDownloadClients,
  useDownloadClientSchema,
  useDownloadSettings,
  useSaveDownloadClient,
  useSaveDownloadSettings,
  useTestDownloadClientSettings,
  useTestSavedDownloadClient,
  useToggleDownloadClient,
} from '../../api/downloads';
import type {
  ClientSettingsValues,
  DownloadClient,
  DownloadClientImplementation,
  ImplementationSchema,
} from '../../api/types';
import { useAddRemotePathMapping, useDeleteRemotePathMapping, useRemotePathMappings } from '../../api/media';
import { ConfirmModal } from '../../components/ConfirmModal';
import { SettingField, TestOutcome } from '../../components/SchemaForm';
import { defaults } from '../../components/settingsDefaults';
import { PageHeader } from '../../components/PageHeader';
import { QueryState } from '../../components/QueryState';
import { t } from '../../i18n';
import { notifyError, notifySuccess } from '../../notify';

function ClientModal({
  schemas,
  client,
  onClose,
}: {
  schemas: ImplementationSchema[];
  client: DownloadClient | null;
  onClose: () => void;
}) {
  const save = useSaveDownloadClient();
  const test = useTestDownloadClientSettings();
  const [implementation, setImplementation] = useState<DownloadClientImplementation>(
    client?.implementation ?? 'sabnzbd',
  );
  const schema = schemas.find((s) => s.implementation === implementation)!;
  const [name, setName] = useState(client?.name ?? schema.name);
  const [priority, setPriority] = useState<number | string>(client?.priority ?? 1);
  const [enabled, setEnabled] = useState(client?.enabled ?? true);
  const [settings, setSettings] = useState<ClientSettingsValues>(client?.settings ?? defaults(schema.fields));

  const switchImplementation = (next: DownloadClientImplementation) => {
    const nextSchema = schemas.find((s) => s.implementation === next)!;
    setImplementation(next);
    setSettings(defaults(nextSchema.fields));
    if (!client) setName(nextSchema.name);
    test.reset();
  };

  const body = { implementation, settings };
  const submit = () =>
    save.mutate(
      { id: client?.id, name, implementation, enabled, priority: Number(priority), settings },
      {
        onSuccess: () => {
          notifySuccess(t('clients.saved'));
          onClose();
        },
        onError: notifyError,
      },
    );

  return (
    <Modal opened onClose={onClose} size="lg" title={client ? t('clients.edit') : t('clients.add')}>
      <Stack>
        <Select
          label={t('clients.field.type')}
          data={schemas.map((s) => ({ value: s.implementation, label: `${s.name} (${t(`search.protocol.${s.protocol}`)})` }))}
          value={implementation}
          allowDeselect={false}
          disabled={client !== null}
          onChange={(v) => v && switchImplementation(v as DownloadClientImplementation)}
        />
        <TextInput label={t('clients.field.name')} withAsterisk value={name} onChange={(e) => setName(e.currentTarget.value)} />
        {schema.fields.map((field) => (
          <SettingField
            key={`${implementation}-${field.name}`}
            field={field}
            value={settings[field.name]}
            onChange={(value) => setSettings((current) => ({ ...current, [field.name]: value }))}
          />
        ))}
        <NumberInput
          label={t('indexers.field.priority')}
          description={t('clients.field.priority.hint')}
          min={1}
          max={50}
          allowDecimal={false}
          value={priority}
          onChange={setPriority}
        />
        <Switch label={t('indexers.field.enabled')} checked={enabled} onChange={(e) => setEnabled(e.currentTarget.checked)} />
        <TestOutcome result={test.data} />
        <Group justify="space-between">
          <Button
            variant="default"
            leftSection={<IconPlugConnected size={16} />}
            loading={test.isPending}
            onClick={() => test.mutate({ ...body, id: client?.id }, { onError: notifyError })}
          >
            {t('common.test')}
          </Button>
          <Group gap="xs">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button onClick={submit} loading={save.isPending} disabled={!name.trim()}>
              {t('common.save')}
            </Button>
          </Group>
        </Group>
      </Stack>
    </Modal>
  );
}

function PathMappings() {
  const mappings = useRemotePathMappings();
  const clients = useDownloadClients();
  const add = useAddRemotePathMapping();
  const remove = useDeleteRemotePathMapping();
  const [host, setHost] = useState('');
  const [remotePath, setRemotePath] = useState('');
  const [localPath, setLocalPath] = useState('');
  const hosts = [...new Set((clients.data ?? []).map((c) => String(c.settings.host ?? '')).filter(Boolean))];

  return (
    <Card withBorder padding="lg">
      <Title order={4} mb="xs">
        {t('mappings.title')}
      </Title>
      <Text size="sm" c="dimmed" mb="md">
        {t('mappings.help')}
      </Text>
      <QueryState isPending={mappings.isPending} error={mappings.error}>
        {() =>
          mappings.data!.length > 0 && (
            <Table mb="md" verticalSpacing="xs">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('mappings.host')}</Table.Th>
                  <Table.Th>{t('mappings.remote')}</Table.Th>
                  <Table.Th>{t('mappings.local')}</Table.Th>
                  <Table.Th w={50} />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {mappings.data!.map((m) => (
                  <Table.Tr key={m.id} data-testid="mapping-row">
                    <Table.Td>{m.host}</Table.Td>
                    <Table.Td ff="monospace">{m.remotePath}</Table.Td>
                    <Table.Td ff="monospace">{m.localPath}</Table.Td>
                    <Table.Td>
                      <ActionIcon variant="subtle" color="red" aria-label={t('mappings.remove', { path: m.remotePath })} onClick={() => remove.mutate(m.id, { onError: notifyError })}>
                        <IconTrash size={16} />
                      </ActionIcon>
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
          add.mutate(
            { host: host.trim(), remotePath: remotePath.trim(), localPath: localPath.trim() },
            {
              onSuccess: () => {
                setRemotePath('');
                setLocalPath('');
                notifySuccess(t('mappings.added'));
              },
              onError: notifyError,
            },
          );
        }}
      >
        <Group align="flex-end" grow>
          <Autocomplete label={t('mappings.host')} data={hosts} value={host} onChange={setHost} placeholder="192.168.1.20" />
          <TextInput label={t('mappings.remote')} value={remotePath} onChange={(e) => setRemotePath(e.currentTarget.value)} placeholder="/data/usenet/complete" />
          <TextInput label={t('mappings.local')} value={localPath} onChange={(e) => setLocalPath(e.currentTarget.value)} placeholder="/downloads" />
          <Button type="submit" loading={add.isPending} disabled={!host.trim() || !remotePath.trim() || !localPath.trim()} style={{ flexGrow: 0 }}>
            {t('rootFolders.add')}
          </Button>
        </Group>
      </form>
    </Card>
  );
}

function FailedHandling() {
  const settings = useDownloadSettings();
  const save = useSaveDownloadSettings();
  return (
    <Card withBorder padding="lg">
      <Title order={4} mb="xs">
        {t('clients.failed.title')}
      </Title>
      <QueryState isPending={settings.isPending} error={settings.error}>
        {() => {
          const current = settings.data!;
          return (
            <Stack>
              <Switch
                label={t('clients.failed.redownload')}
                description={t('clients.failed.redownload.hint')}
                checked={current.redownloadFailed}
                onChange={(e) => save.mutate({ ...current, redownloadFailed: e.currentTarget.checked }, { onError: notifyError })}
              />
              <NumberInput
                label={t('clients.failed.maxRetries')}
                description={t('clients.failed.maxRetries.hint')}
                min={0}
                max={20}
                allowDecimal={false}
                disabled={!current.redownloadFailed}
                defaultValue={current.maxRetries}
                maw={320}
                onBlur={(e) => {
                  const value = Number(e.currentTarget.value);
                  if (Number.isInteger(value) && value >= 0 && value <= 20 && value !== current.maxRetries) {
                    save.mutate({ ...current, maxRetries: value }, { onError: notifyError });
                  }
                }}
              />
            </Stack>
          );
        }}
      </QueryState>
    </Card>
  );
}

export function DownloadClientsPage() {
  const clients = useDownloadClients();
  const schemas = useDownloadClientSchema();
  const toggle = useToggleDownloadClient();
  const testSaved = useTestSavedDownloadClient();
  const remove = useDeleteDownloadClient();
  const [editing, setEditing] = useState<DownloadClient | 'new' | null>(null);
  const [deleting, setDeleting] = useState<DownloadClient | null>(null);

  const runTest = (client: DownloadClient) =>
    testSaved.mutate(client.id, {
      onSuccess: (result) =>
        result.ok
          ? notifySuccess([result.message, ...result.warnings].join('. '))
          : notifyError(new Error(result.message)),
      onError: notifyError,
    });

  return (
    <Stack gap="lg" maw={1000}>
      <PageHeader title={t('nav.settings.clients')}>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setEditing('new')} disabled={!schemas.data}>
          {t('clients.add')}
        </Button>
      </PageHeader>
      <Card withBorder padding="lg">
        <Text size="sm" c="dimmed" mb="md">
          {t('clients.help')}
        </Text>
        <QueryState isPending={clients.isPending} error={clients.error}>
          {() =>
            clients.data!.length === 0 ? (
              <Text c="dimmed" size="sm">
                {t('clients.empty')}
              </Text>
            ) : (
              <Table verticalSpacing="xs">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>{t('indexers.column.name')}</Table.Th>
                    <Table.Th>{t('clients.column.type')}</Table.Th>
                    <Table.Th>{t('indexers.column.priority')}</Table.Th>
                    <Table.Th>{t('clients.column.category')}</Table.Th>
                    <Table.Th>{t('indexers.column.enabled')}</Table.Th>
                    <Table.Th w={110} />
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {clients.data!.map((client) => (
                    <Table.Tr key={client.id} data-testid="client-row">
                      <Table.Td fw={500}>{client.name}</Table.Td>
                      <Table.Td>
                        <Group gap={6}>
                          <Text size="sm">{schemas.data?.find((s) => s.implementation === client.implementation)?.name}</Text>
                          <Badge variant="light" color={client.protocol === 'torrent' ? 'grape' : 'blue'} style={{ minWidth: 'max-content' }}>
                            {t(`search.protocol.${client.protocol}`)}
                          </Badge>
                        </Group>
                      </Table.Td>
                      <Table.Td>{client.priority}</Table.Td>
                      <Table.Td>{String(client.settings.category ?? '') || '—'}</Table.Td>
                      <Table.Td>
                        <Switch
                          aria-label={t('indexers.toggle', { name: client.name })}
                          checked={client.enabled}
                          onChange={(e) => toggle.mutate({ id: client.id, enabled: e.currentTarget.checked }, { onError: notifyError })}
                        />
                      </Table.Td>
                      <Table.Td>
                        <Group gap={2} justify="flex-end" wrap="nowrap">
                          <ActionIcon variant="subtle" aria-label={t('indexers.testNamed', { name: client.name })} onClick={() => runTest(client)}>
                            <IconPlugConnected size={16} />
                          </ActionIcon>
                          <ActionIcon variant="subtle" aria-label={t('indexers.editNamed', { name: client.name })} onClick={() => setEditing(client)}>
                            <IconEdit size={16} />
                          </ActionIcon>
                          <ActionIcon variant="subtle" color="red" aria-label={t('indexers.deleteNamed', { name: client.name })} onClick={() => setDeleting(client)}>
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
      </Card>
      <PathMappings />
      <FailedHandling />
      {editing && schemas.data && (
        <ClientModal
          key={editing === 'new' ? 'new' : editing.id}
          schemas={schemas.data}
          client={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}
      <ConfirmModal
        opened={deleting !== null}
        title={t('clients.delete.title')}
        message={t('clients.delete.message', { name: deleting?.name ?? '' })}
        confirmLabel={t('common.delete')}
        loading={remove.isPending}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id, { onSuccess: () => setDeleting(null), onError: notifyError })}
      />
    </Stack>
  );
}
