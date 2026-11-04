import { ActionIcon, Anchor, Badge, Button, Checkbox, Group, Modal, Progress, Stack, Table, Text, Tooltip } from '@mantine/core';
import { IconFileImport, IconRefresh, IconTrash } from '@tabler/icons-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { useQueue, useRemoveFromQueue, useRetryImport } from '../../api/activity';
import type { Download } from '../../api/types';
import { PageHeader } from '../../components/PageHeader';
import { QueryState } from '../../components/QueryState';
import { DownloadBadge } from '../../components/StatusBadge';
import { formatBytes } from '../../format';
import { t } from '../../i18n';
import { notifyError, notifySuccess } from '../../notify';

function RemoveModal({ download, onClose }: { download: Download; onClose: () => void }) {
  const remove = useRemoveFromQueue();
  const [removeFromClient, setRemoveFromClient] = useState(true);
  const [blocklist, setBlocklist] = useState(false);
  return (
    <Modal opened onClose={onClose} title={t('queue.remove.title')} centered>
      <Stack>
        <Text size="sm">{download.title}</Text>
        <Checkbox label={t('queue.remove.fromClient')} checked={removeFromClient} onChange={(e) => setRemoveFromClient(e.currentTarget.checked)} />
        <Checkbox label={t('queue.remove.blocklist')} checked={blocklist} onChange={(e) => setBlocklist(e.currentTarget.checked)} />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            color="red"
            loading={remove.isPending}
            onClick={() =>
              remove.mutate(
                { id: download.id, removeFromClient, blocklist },
                {
                  onSuccess: () => {
                    notifySuccess(t('queue.removed'));
                    onClose();
                  },
                  onError: notifyError,
                },
              )
            }
          >
            {t('queue.remove')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

export function QueuePage() {
  const { data, isPending, error, live } = useQueue();
  const retry = useRetryImport();
  const [removing, setRemoving] = useState<Download | null>(null);

  return (
    <Stack gap="lg">
      <PageHeader title={t('nav.activity.queue')}>
        <Badge variant="dot" color={live ? 'teal' : 'gray'}>
          {live ? t('queue.live') : t('queue.polling')}
        </Badge>
      </PageHeader>
      <QueryState isPending={isPending} error={error}>
        {() =>
          data!.length === 0 ? (
            <Text c="dimmed">{t('queue.empty')}</Text>
          ) : (
            <Table.ScrollContainer minWidth={900}>
              <Table verticalSpacing="sm">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>{t('queue.column.issue')}</Table.Th>
                    <Table.Th>{t('search.column.title')}</Table.Th>
                    <Table.Th>{t('issues.column.status')}</Table.Th>
                    <Table.Th w={160}>{t('queue.column.progress')}</Table.Th>
                    <Table.Th ta="right">{t('search.column.size')}</Table.Th>
                    <Table.Th w={110} />
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {data!.map((download) => {
                    const importable = download.status === 'pending_import' || download.status === 'import_blocked';
                    return (
                      <Table.Tr key={download.id} data-testid="queue-row">
                        <Table.Td>
                          {download.magazineId ? (
                            <Anchor component={Link} to={`/magazine/${download.magazineId}`} size="sm">
                              {download.magazineTitle} · {download.issueNumber}
                            </Anchor>
                          ) : (
                            '—'
                          )}
                        </Table.Td>
                        <Table.Td>
                          <Text size="sm" ff="monospace" style={{ overflowWrap: 'anywhere' }}>
                            {download.title}
                          </Text>
                          {download.message && (
                            <Text size="xs" c={download.status === 'import_blocked' ? 'orange' : 'dimmed'}>
                              {download.message}
                            </Text>
                          )}
                        </Table.Td>
                        <Table.Td>
                          <DownloadBadge download={download} />
                        </Table.Td>
                        <Table.Td>
                          <Progress value={download.progress * 100} size="sm" aria-label={t('queue.column.progress')} />
                        </Table.Td>
                        <Table.Td ta="right" style={{ whiteSpace: 'nowrap' }}>
                          {formatBytes(download.size)}
                        </Table.Td>
                        <Table.Td>
                          <Group gap={2} justify="flex-end" wrap="nowrap">
                            {importable && (
                              <>
                                <Tooltip label={t('queue.retry')}>
                                  <ActionIcon
                                    variant="subtle"
                                    aria-label={t('queue.retryNamed', { title: download.title })}
                                    loading={retry.isPending && retry.variables === download.id}
                                    onClick={() =>
                                      retry.mutate(download.id, {
                                        onSuccess: (result) =>
                                          result.status === 'imported'
                                            ? notifySuccess(t('queue.imported', { title: result.title }))
                                            : notifyError(new Error(result.message ?? t('download.status.import_blocked'))),
                                        onError: notifyError,
                                      })
                                    }
                                  >
                                    <IconRefresh size={16} />
                                  </ActionIcon>
                                </Tooltip>
                                <Tooltip label={t('queue.manual')}>
                                  <ActionIcon
                                    variant="subtle"
                                    component={Link}
                                    to={`/activity/import?downloadId=${download.id}`}
                                    aria-label={t('queue.manualNamed', { title: download.title })}
                                  >
                                    <IconFileImport size={16} />
                                  </ActionIcon>
                                </Tooltip>
                              </>
                            )}
                            <ActionIcon
                              variant="subtle"
                              color="red"
                              aria-label={t('queue.removeNamed', { title: download.title })}
                              onClick={() => setRemoving(download)}
                            >
                              <IconTrash size={16} />
                            </ActionIcon>
                          </Group>
                        </Table.Td>
                      </Table.Tr>
                    );
                  })}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )
        }
      </QueryState>
      {removing && <RemoveModal download={removing} onClose={() => setRemoving(null)} />}
    </Stack>
  );
}
