import { ActionIcon, Badge, Button, Card, FileButton, Group, Loader, Modal, Stack, Table, Text } from '@mantine/core';
import { IconDownload, IconFileUpload, IconRestore, IconTrash, IconPlus } from '@tabler/icons-react';
import { useEffect, useState } from 'react';

import { saveApiFile } from '../../api/client';
import { useBackups, useCreateBackup, useDeleteBackup, useRestoreBackup } from '../../api/systemPages';
import type { Backup } from '../../api/types';
import { ConfirmModal } from '../../components/ConfirmModal';
import { PageHeader } from '../../components/PageHeader';
import { QueryState } from '../../components/QueryState';
import { formatBytes } from '../../format';
import { t } from '../../i18n';
import { notifyError, notifySuccess } from '../../notify';

const KIND_COLORS: Record<Backup['kind'], string> = { manual: 'blue', scheduled: 'gray', pre_restore: 'orange' };

/** Shown while Magarr restarts to apply a restore; reloads once it answers again. */
function Restarting() {
  useEffect(() => {
    let cancelled = false;
    const started = Date.now();
    const poll = async () => {
      // Give it a moment to go down before waiting for it to come back.
      await new Promise((resolve) => setTimeout(resolve, 3000));
      while (!cancelled && Date.now() - started < 5 * 60_000) {
        try {
          if ((await fetch('/health', { cache: 'no-store' })).ok) {
            window.location.reload();
            return;
          }
        } catch {
          // Still restarting.
        }
        await new Promise((resolve) => setTimeout(resolve, 2000));
      }
    };
    void poll();
    return () => {
      cancelled = true;
    };
  }, []);
  return (
    <Modal opened onClose={() => {}} withCloseButton={false} centered title={t('backup.restarting.title')}>
      <Group gap="sm">
        <Loader size="sm" />
        <Text size="sm">{t('backup.restarting.body')}</Text>
      </Group>
    </Modal>
  );
}

export function BackupPage() {
  const backups = useBackups();
  const create = useCreateBackup();
  const remove = useDeleteBackup();
  const restore = useRestoreBackup();
  const [restoring, setRestoring] = useState<{ name: string } | { file: File } | null>(null);
  const [deleting, setDeleting] = useState<Backup | null>(null);
  const [restarting, setRestarting] = useState(false);

  const confirmRestore = () =>
    restoring &&
    restore.mutate(restoring, {
      onSuccess: () => {
        setRestoring(null);
        setRestarting(true);
      },
      onError: (error) => {
        setRestoring(null);
        notifyError(error);
      },
    });

  return (
    <Stack gap="lg" maw={1000}>
      <PageHeader title={t('nav.system.backup')}>
        <FileButton onChange={(file) => file && setRestoring({ file })} accept=".zip,application/zip">
          {(props) => (
            <Button variant="default" leftSection={<IconFileUpload size={16} />} {...props}>
              {t('backup.upload')}
            </Button>
          )}
        </FileButton>
        <Button
          leftSection={<IconPlus size={16} />}
          loading={create.isPending}
          onClick={() => create.mutate(undefined, { onSuccess: (b) => notifySuccess(t('backup.created', { name: b.name })), onError: notifyError })}
        >
          {t('backup.now')}
        </Button>
      </PageHeader>
      <Card withBorder padding="lg">
        <Text size="sm" c="dimmed" mb="md">
          {t('backup.help')}
        </Text>
        <QueryState isPending={backups.isPending} error={backups.error}>
          {() =>
            backups.data!.length === 0 ? (
              <Text c="dimmed" size="sm">
                {t('backup.empty')}
              </Text>
            ) : (
              <Table.ScrollContainer minWidth={700}>
                <Table verticalSpacing="xs">
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>{t('backup.column.name')}</Table.Th>
                      <Table.Th>{t('backup.column.type')}</Table.Th>
                      <Table.Th>{t('backup.column.size')}</Table.Th>
                      <Table.Th>{t('backup.column.created')}</Table.Th>
                      <Table.Th w={110} />
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {backups.data!.map((backup) => (
                      <Table.Tr key={backup.name} data-testid="backup-row">
                        <Table.Td ff="monospace" fz="sm">
                          {backup.name}
                        </Table.Td>
                        <Table.Td>
                          <Badge variant="light" color={KIND_COLORS[backup.kind]}>
                            {t(`backup.kind.${backup.kind}`)}
                          </Badge>
                        </Table.Td>
                        <Table.Td>{formatBytes(backup.size)}</Table.Td>
                        <Table.Td style={{ whiteSpace: 'nowrap' }}>{new Date(backup.created).toLocaleString()}</Table.Td>
                        <Table.Td>
                          <Group gap={2} justify="flex-end" wrap="nowrap">
                            <ActionIcon
                              variant="subtle"
                              aria-label={t('backup.download', { name: backup.name })}
                              onClick={() => saveApiFile(`/api/v1/system/backup/${encodeURIComponent(backup.name)}`, backup.name).catch(notifyError)}
                            >
                              <IconDownload size={16} />
                            </ActionIcon>
                            <ActionIcon variant="subtle" aria-label={t('backup.restore', { name: backup.name })} onClick={() => setRestoring({ name: backup.name })}>
                              <IconRestore size={16} />
                            </ActionIcon>
                            <ActionIcon variant="subtle" color="red" aria-label={t('backup.delete', { name: backup.name })} onClick={() => setDeleting(backup)}>
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
      <ConfirmModal
        opened={restoring !== null}
        title={t('backup.restore.title')}
        message={t('backup.restore.message', {
          name: restoring ? ('name' in restoring ? restoring.name : restoring.file.name) : '',
        })}
        confirmLabel={t('backup.restore.confirm')}
        loading={restore.isPending}
        onClose={() => setRestoring(null)}
        onConfirm={confirmRestore}
      />
      <ConfirmModal
        opened={deleting !== null}
        title={t('backup.delete.title')}
        message={t('backup.delete.message', { name: deleting?.name ?? '' })}
        confirmLabel={t('common.delete')}
        loading={remove.isPending}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.name, { onSuccess: () => setDeleting(null), onError: notifyError })}
      />
      {restarting && <Restarting />}
    </Stack>
  );
}
