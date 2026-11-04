import {
  Accordion,
  ActionIcon,
  Badge,
  Button,
  Card,
  Checkbox,
  Code,
  Group,
  Modal,
  Paper,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  Textarea,
  TextInput,
  Tooltip,
} from '@mantine/core';
import { IconAlertTriangle, IconEdit, IconEye, IconPlugConnected, IconPlus, IconTrash } from '@tabler/icons-react';
import { useState } from 'react';

import {
  useDeleteNotification,
  useNotifications,
  useNotificationSchema,
  usePreviewTemplate,
  useSaveNotification,
  useTestNotificationSettings,
  useTestSavedNotification,
  useToggleNotification,
} from '../../api/notifications';
import type {
  ClientSettingsValues,
  Notification,
  NotificationEvent,
  NotificationImplementation,
  NotificationSchema,
} from '../../api/types';
import { ConfirmModal } from '../../components/ConfirmModal';
import { PageHeader } from '../../components/PageHeader';
import { QueryState } from '../../components/QueryState';
import { SettingField, TestOutcome } from '../../components/SchemaForm';
import { defaults } from '../../components/settingsDefaults';
import { t } from '../../i18n';
import { notifyError, notifySuccess } from '../../notify';

const EVENT_COLORS: Record<NotificationEvent, string> = {
  grab: 'blue',
  import: 'teal',
  upgrade: 'cyan',
  failure: 'red',
  health: 'orange',
};

function TemplateEditor({
  schema,
  event,
  value,
  onChange,
}: {
  schema: NotificationSchema;
  event: NotificationEvent;
  value: string;
  onChange: (value: string) => void;
}) {
  const preview = usePreviewTemplate();
  const template = value || schema.defaultTemplates[event];
  return (
    <Stack gap="xs">
      <Textarea
        label={t(`notifications.event.${event}`)}
        description={t('notifications.template.hint')}
        placeholder={schema.defaultTemplates[event]}
        autosize
        minRows={2}
        value={value}
        onChange={(e) => onChange(e.currentTarget.value)}
        styles={{ input: { fontFamily: 'var(--mantine-font-family-monospace)' } }}
      />
      <Group gap="xs">
        <Button
          size="compact-xs"
          variant="default"
          leftSection={<IconEye size={12} />}
          loading={preview.isPending}
          onClick={() => preview.mutate(template, { onError: notifyError })}
        >
          {t('notifications.preview')}
        </Button>
        {value && (
          <Button size="compact-xs" variant="subtle" onClick={() => onChange('')}>
            {t('notifications.template.reset')}
          </Button>
        )}
      </Group>
      {preview.data && (
        <Paper withBorder p="xs" data-testid={`preview-${event}`}>
          <Text size="sm" fw={600}>
            {preview.data.title}
          </Text>
          <Text size="sm" style={{ whiteSpace: 'pre-line' }}>
            {preview.data.body}
          </Text>
        </Paper>
      )}
    </Stack>
  );
}

function NotificationModal({
  schema,
  notification,
  onClose,
}: {
  schema: NotificationSchema;
  notification: Notification | null;
  onClose: () => void;
}) {
  const save = useSaveNotification();
  const test = useTestNotificationSettings();
  const [implementation, setImplementation] = useState<NotificationImplementation>(
    notification?.implementation ?? 'discord',
  );
  const service = schema.implementations.find((i) => i.implementation === implementation)!;
  const [name, setName] = useState(notification?.name ?? service.name);
  const [enabled, setEnabled] = useState(notification?.enabled ?? true);
  const [events, setEvents] = useState<NotificationEvent[]>(notification?.events ?? schema.events);
  const [settings, setSettings] = useState<ClientSettingsValues>(notification?.settings ?? defaults(service.fields));
  const [templates, setTemplates] = useState<Partial<Record<NotificationEvent, string>>>(notification?.templates ?? {});

  const switchService = (next: NotificationImplementation) => {
    const nextService = schema.implementations.find((i) => i.implementation === next)!;
    setImplementation(next);
    setSettings(defaults(nextService.fields));
    if (!notification) setName(nextService.name);
    test.reset();
  };

  const submit = () =>
    save.mutate(
      { id: notification?.id, name, implementation, enabled, events, settings, templates },
      {
        onSuccess: () => {
          notifySuccess(t('notifications.saved'));
          onClose();
        },
        onError: notifyError,
      },
    );

  return (
    <Modal opened onClose={onClose} size="lg" title={notification ? t('notifications.edit') : t('notifications.add')}>
      <Stack>
        <Select
          label={t('notifications.field.service')}
          data={schema.implementations.map((i) => ({ value: i.implementation, label: i.name }))}
          value={implementation}
          allowDeselect={false}
          disabled={notification !== null}
          onChange={(v) => v && switchService(v as NotificationImplementation)}
        />
        <TextInput label={t('clients.field.name')} withAsterisk value={name} onChange={(e) => setName(e.currentTarget.value)} />
        {service.fields.map((field) => (
          <SettingField
            key={`${implementation}-${field.name}`}
            field={field}
            value={settings[field.name]}
            onChange={(value) => setSettings((current) => ({ ...current, [field.name]: value }))}
          />
        ))}
        <Checkbox.Group
          label={t('notifications.field.events')}
          description={t('notifications.field.events.hint')}
          value={events}
          onChange={(value) => setEvents(value as NotificationEvent[])}
        >
          <Group mt="xs">
            {schema.events.map((event) => (
              <Checkbox key={event} value={event} label={t(`notifications.event.${event}`)} />
            ))}
          </Group>
        </Checkbox.Group>
        <Accordion variant="contained">
          <Accordion.Item value="templates">
            <Accordion.Control>{t('notifications.templates')}</Accordion.Control>
            <Accordion.Panel>
              <Stack>
                <Text size="xs" c="dimmed">
                  {t('notifications.tokens')}{' '}
                  {schema.tokens.map((token) => (
                    <Tooltip key={token.name} label={token.description}>
                      <Code mr={4}>{`{${token.name}}`}</Code>
                    </Tooltip>
                  ))}
                </Text>
                {events.map((event) => (
                  <TemplateEditor
                    key={event}
                    schema={schema}
                    event={event}
                    value={templates[event] ?? ''}
                    onChange={(value) => setTemplates((current) => ({ ...current, [event]: value }))}
                  />
                ))}
              </Stack>
            </Accordion.Panel>
          </Accordion.Item>
        </Accordion>
        <Switch label={t('indexers.field.enabled')} checked={enabled} onChange={(e) => setEnabled(e.currentTarget.checked)} />
        <TestOutcome result={test.data} />
        <Group justify="space-between">
          <Button
            variant="default"
            leftSection={<IconPlugConnected size={16} />}
            loading={test.isPending}
            onClick={() => test.mutate({ implementation, settings, id: notification?.id }, { onError: notifyError })}
          >
            {t('notifications.sendTest')}
          </Button>
          <Group gap="xs">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button onClick={submit} loading={save.isPending} disabled={!name.trim() || events.length === 0}>
              {t('common.save')}
            </Button>
          </Group>
        </Group>
      </Stack>
    </Modal>
  );
}

export function NotificationsPage() {
  const notifications = useNotifications();
  const schema = useNotificationSchema();
  const toggle = useToggleNotification();
  const testSaved = useTestSavedNotification();
  const remove = useDeleteNotification();
  const [editing, setEditing] = useState<Notification | 'new' | null>(null);
  const [deleting, setDeleting] = useState<Notification | null>(null);
  const serviceName = (n: Notification) =>
    schema.data?.implementations.find((i) => i.implementation === n.implementation)?.name ?? n.implementation;

  const runTest = (n: Notification) =>
    testSaved.mutate(n.id, {
      onSuccess: (result) => (result.ok ? notifySuccess(result.message) : notifyError(new Error(result.message))),
      onError: notifyError,
    });

  return (
    <Stack gap="lg" maw={1000}>
      <PageHeader title={t('nav.settings.notifications')}>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setEditing('new')} disabled={!schema.data}>
          {t('notifications.add')}
        </Button>
      </PageHeader>
      <Card withBorder padding="lg">
        <Text size="sm" c="dimmed" mb="md">
          {t('notifications.help')}
        </Text>
        <QueryState isPending={notifications.isPending} error={notifications.error}>
          {() =>
            notifications.data!.length === 0 ? (
              <Text c="dimmed" size="sm">
                {t('notifications.empty')}
              </Text>
            ) : (
              <Table.ScrollContainer minWidth={700}>
                <Table verticalSpacing="xs">
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>{t('indexers.column.name')}</Table.Th>
                      <Table.Th>{t('notifications.column.service')}</Table.Th>
                      <Table.Th>{t('notifications.column.events')}</Table.Th>
                      <Table.Th>{t('indexers.column.enabled')}</Table.Th>
                      <Table.Th w={110} />
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {notifications.data!.map((n) => (
                      <Table.Tr key={n.id} data-testid="notification-row">
                        <Table.Td fw={500}>
                          <Group gap={6} wrap="nowrap">
                            {n.name}
                            {n.lastError && (
                              <Tooltip label={n.lastError} multiline w={300}>
                                <IconAlertTriangle size={16} color="var(--mantine-color-red-5)" aria-label={n.lastError} />
                              </Tooltip>
                            )}
                          </Group>
                        </Table.Td>
                        <Table.Td>{serviceName(n)}</Table.Td>
                        <Table.Td>
                          <Group gap={4}>
                            {n.events.map((event) => (
                              <Badge key={event} size="sm" variant="light" color={EVENT_COLORS[event]}>
                                {t(`notifications.event.${event}`)}
                              </Badge>
                            ))}
                          </Group>
                        </Table.Td>
                        <Table.Td>
                          <Switch
                            aria-label={t('indexers.toggle', { name: n.name })}
                            checked={n.enabled}
                            onChange={(e) => toggle.mutate({ id: n.id, enabled: e.currentTarget.checked }, { onError: notifyError })}
                          />
                        </Table.Td>
                        <Table.Td>
                          <Group gap={2} justify="flex-end" wrap="nowrap">
                            <ActionIcon variant="subtle" aria-label={t('indexers.testNamed', { name: n.name })} onClick={() => runTest(n)}>
                              <IconPlugConnected size={16} />
                            </ActionIcon>
                            <ActionIcon variant="subtle" aria-label={t('indexers.editNamed', { name: n.name })} onClick={() => setEditing(n)}>
                              <IconEdit size={16} />
                            </ActionIcon>
                            <ActionIcon variant="subtle" color="red" aria-label={t('indexers.deleteNamed', { name: n.name })} onClick={() => setDeleting(n)}>
                              <IconTrash size={16} />
                            </ActionIcon>
                          </Group>
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Table.ScrollContainer>
            )
          }
        </QueryState>
      </Card>
      {editing && schema.data && (
        <NotificationModal
          key={editing === 'new' ? 'new' : editing.id}
          schema={schema.data}
          notification={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}
      <ConfirmModal
        opened={deleting !== null}
        title={t('notifications.delete.title')}
        message={t('notifications.delete.message', { name: deleting?.name ?? '' })}
        confirmLabel={t('common.delete')}
        loading={remove.isPending}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id, { onSuccess: () => setDeleting(null), onError: notifyError })}
      />
    </Stack>
  );
}
