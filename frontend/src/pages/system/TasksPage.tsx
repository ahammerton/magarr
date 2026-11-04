import { ActionIcon, Badge, Card, Drawer, Group, Loader, Stack, Table, Text, Tooltip } from '@mantine/core';
import { IconHistory, IconPlayerPlay } from '@tabler/icons-react';
import { useState } from 'react';

import { useRunTask, useTaskHistory, useTasks } from '../../api/systemPages';
import type { Task } from '../../api/types';
import { PageHeader } from '../../components/PageHeader';
import { QueryState } from '../../components/QueryState';
import { formatInterval, formatRelative } from '../../format';
import { t } from '../../i18n';
import { notifyError, notifySuccess } from '../../notify';

function schedule(task: Task): string {
  if (task.paused) return t('tasks.paused');
  if (task.intervalMinutes <= 0) return t('tasks.off');
  return formatInterval(task.intervalMinutes);
}

function History({ task, onClose }: { task: Task | null; onClose: () => void }) {
  const history = useTaskHistory(task?.name ?? null);
  return (
    <Drawer opened={task !== null} onClose={onClose} position="right" size="lg" title={task ? t('tasks.history', { task: task.label }) : ''}>
      <QueryState isPending={history.isPending} error={history.error}>
        {() =>
          history.data!.length === 0 ? (
            <Text c="dimmed" size="sm">
              {t('tasks.history.empty')}
            </Text>
          ) : (
            <Table verticalSpacing="xs">
              <Table.Tbody>
                {history.data!.map((run) => (
                  <Table.Tr key={run.id} data-testid="task-run">
                    <Table.Td style={{ whiteSpace: 'nowrap' }}>
                      <Text size="sm">{new Date(run.startedAt).toLocaleString()}</Text>
                      {run.manual && (
                        <Text size="xs" c="dimmed">
                          {t('tasks.manual')}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" c={run.ok ? undefined : 'red'}>
                        {run.result}
                      </Text>
                    </Table.Td>
                    <Table.Td ta="right" style={{ whiteSpace: 'nowrap' }}>
                      <Text size="xs" c="dimmed">
                        {(run.durationMs / 1000).toFixed(1)} s
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )
        }
      </QueryState>
    </Drawer>
  );
}

export function TasksPage() {
  const tasks = useTasks();
  const run = useRunTask();
  const [viewing, setViewing] = useState<Task | null>(null);
  return (
    <Stack gap="lg">
      <PageHeader title={t('nav.system.tasks')} />
      <Card withBorder padding="sm">
        <QueryState isPending={tasks.isPending} error={tasks.error}>
          {() => (
            <Table.ScrollContainer minWidth={820}>
              <Table verticalSpacing="xs">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>{t('tasks.column.task')}</Table.Th>
                    <Table.Th>{t('tasks.column.schedule')}</Table.Th>
                    <Table.Th>{t('tasks.column.lastRun')}</Table.Th>
                    <Table.Th>{t('tasks.column.result')}</Table.Th>
                    <Table.Th>{t('tasks.column.nextRun')}</Table.Th>
                    <Table.Th w={80} />
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {tasks.data!.map((task) => (
                    <Table.Tr key={task.name} data-testid="task-row">
                      <Table.Td fw={500}>{task.label}</Table.Td>
                      <Table.Td>
                        <Text size="sm" c={task.paused ? 'orange' : undefined}>
                          {schedule(task)}
                        </Text>
                      </Table.Td>
                      <Table.Td style={{ whiteSpace: 'nowrap' }}>
                        <Tooltip label={task.lastRun ? new Date(task.lastRun).toLocaleString() : ''} disabled={!task.lastRun}>
                          <Text size="sm">{task.lastRun ? formatRelative(task.lastRun) : t('automation.notYet')}</Text>
                        </Tooltip>
                      </Table.Td>
                      <Table.Td>
                        {task.lastResult && (
                          <Group gap={6} wrap="nowrap">
                            {!task.lastOk && (
                              <Badge color="red" size="sm" variant="light">
                                {t('tasks.failed')}
                              </Badge>
                            )}
                            <Text size="sm">{task.lastResult}</Text>
                          </Group>
                        )}
                      </Table.Td>
                      <Table.Td style={{ whiteSpace: 'nowrap' }}>
                        <Text size="sm" c="dimmed">
                          {task.nextRun ? formatRelative(task.nextRun) : '—'}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Group gap={2} justify="flex-end" wrap="nowrap">
                          {task.running ? (
                            <Loader size="xs" aria-label={t('tasks.running', { task: task.label })} />
                          ) : (
                            <ActionIcon
                              variant="subtle"
                              aria-label={t('tasks.runNow', { task: task.label })}
                              onClick={() =>
                                run.mutate(task.name, {
                                  onSuccess: () => notifySuccess(t('tasks.started', { task: task.label })),
                                  onError: notifyError,
                                })
                              }
                            >
                              <IconPlayerPlay size={16} />
                            </ActionIcon>
                          )}
                          {task.name !== 'downloads' && (
                            <ActionIcon variant="subtle" aria-label={t('tasks.historyNamed', { task: task.label })} onClick={() => setViewing(task)}>
                              <IconHistory size={16} />
                            </ActionIcon>
                          )}
                        </Group>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}
        </QueryState>
      </Card>
      <History task={viewing} onClose={() => setViewing(null)} />
    </Stack>
  );
}
