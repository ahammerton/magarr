import { ActionIcon, Badge, Button, Card, Code, Grid, Group, Stack, Text, Title, Tooltip } from '@mantine/core';
import {
  IconBookmark,
  IconBookmarkOff,
  IconCalendarPlus,
  IconEdit,
  IconPlus,
  IconTrash,
} from '@tabler/icons-react';
import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { useDeleteMagazine, useIssues, useMagazine, useUpdateMagazine } from '../../api/magazines';
import type { Magazine } from '../../api/types';
import { ConfirmModal } from '../../components/ConfirmModal';
import { EmptyPage } from '../../components/EmptyPage';
import { Poster } from '../../components/Poster';
import { QueryState } from '../../components/QueryState';
import { formatBytes } from '../../format';
import { t } from '../../i18n';
import { notifyError, notifySuccess } from '../../notify';
import { IssueTable } from './IssueTable';
import { EditMagazineModal, GenerateIssuesModal, IssueModal } from './MagazineModals';

type ModalName = 'edit' | 'generate' | 'addIssue' | 'delete' | null;

function Header({ magazine, onOpen }: { magazine: Magazine; onOpen: (m: ModalName) => void }) {
  const update = useUpdateMagazine(magazine.id);
  const { issueCount, downloadedCount, wantedCount, sizeOnDisk } = magazine.statistics;

  return (
    <Card withBorder padding="lg">
      <Grid gutter="lg">
        <Grid.Col span={{ base: 4, sm: 3, md: 2 }}>
          <Poster title={magazine.title} url={magazine.posterUrl} coverUrl={magazine.coverUrl} />
        </Grid.Col>
        <Grid.Col span={{ base: 12, sm: 9, md: 10 }}>
          <Stack gap="sm">
            <Group justify="space-between" align="flex-start" wrap="wrap">
              <Group gap="xs">
                <Tooltip label={magazine.monitored ? t('magazine.unmonitor') : t('magazine.monitor')}>
                  <ActionIcon
                    variant="subtle"
                    size="lg"
                    color={magazine.monitored ? 'violet' : 'gray'}
                    aria-label={magazine.monitored ? t('magazine.unmonitor') : t('magazine.monitor')}
                    loading={update.isPending}
                    onClick={() => update.mutate({ monitored: !magazine.monitored }, { onError: notifyError })}
                  >
                    {magazine.monitored ? <IconBookmark /> : <IconBookmarkOff />}
                  </ActionIcon>
                </Tooltip>
                <Title order={2}>{magazine.title}</Title>
              </Group>
              <Group gap="xs">
                <Button variant="default" size="xs" leftSection={<IconCalendarPlus size={16} />} onClick={() => onOpen('generate')}>
                  {t('magazine.generate')}
                </Button>
                <Button variant="default" size="xs" leftSection={<IconPlus size={16} />} onClick={() => onOpen('addIssue')}>
                  {t('issue.add')}
                </Button>
                <Button variant="default" size="xs" leftSection={<IconEdit size={16} />} onClick={() => onOpen('edit')}>
                  {t('common.edit')}
                </Button>
                <Button variant="default" size="xs" color="red" leftSection={<IconTrash size={16} />} onClick={() => onOpen('delete')}>
                  {t('common.delete')}
                </Button>
              </Group>
            </Group>
            {magazine.alternateTitles.length > 0 && (
              <Text size="sm" c="dimmed">
                {t('magazine.aka', { titles: magazine.alternateTitles.join(', ') })}
              </Text>
            )}
            <Group gap="xs">
              <Badge variant="light">{t(`frequency.${magazine.frequency}`)}</Badge>
              {magazine.category && <Badge variant="light" color="gray">{magazine.category}</Badge>}
              <Badge variant="light" color="gray">{magazine.language}</Badge>
              {magazine.firstIssueYear && (
                <Badge variant="light" color="gray">
                  {t('magazine.since', { year: magazine.firstIssueYear })}
                </Badge>
              )}
              {magazine.tags.map((tag) => (
                <Badge key={tag} variant="outline" color="gray">
                  {tag}
                </Badge>
              ))}
            </Group>
            {magazine.publisher && <Text size="sm">{magazine.publisher}</Text>}
            <Code>{magazine.path}</Code>
            <Group gap="xl">
              <Stat label={t('magazine.stat.issues')} value={`${downloadedCount}/${issueCount}`} />
              <Stat label={t('magazine.stat.wanted')} value={String(wantedCount)} />
              <Stat label={t('magazine.stat.size')} value={formatBytes(sizeOnDisk)} />
            </Group>
            {magazine.notes && (
              <Text size="sm" c="dimmed" style={{ whiteSpace: 'pre-wrap' }}>
                {magazine.notes}
              </Text>
            )}
          </Stack>
        </Grid.Col>
      </Grid>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
        {label}
      </Text>
      <Text fw={600}>{value}</Text>
    </div>
  );
}

export function MagazineDetailPage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const magazine = useMagazine(id);
  const issues = useIssues(id);
  const remove = useDeleteMagazine();
  const [modal, setModal] = useState<ModalName>(null);
  const close = () => setModal(null);

  if (magazine.error && 'status' in magazine.error && magazine.error.status === 404) {
    return <EmptyPage title="page.notFound.title" description="magazine.notFound" />;
  }

  return (
    <QueryState isPending={magazine.isPending} error={magazine.error}>
      {() => (
        <Stack gap="lg">
          <Header magazine={magazine.data!} onOpen={setModal} />
          <QueryState isPending={issues.isPending} error={issues.error}>
            {() => <IssueTable magazineId={id} issues={issues.data!} />}
          </QueryState>

          {modal === 'edit' && <EditMagazineModal magazine={magazine.data!} opened onClose={close} />}
          {modal === 'generate' && (
            <GenerateIssuesModal magazine={magazine.data!} issues={issues.data ?? []} opened onClose={close} />
          )}
          {modal === 'addIssue' && <IssueModal magazineId={id} opened onClose={close} />}
          <ConfirmModal
            opened={modal === 'delete'}
            title={t('magazine.delete.title')}
            message={t('magazine.delete.message', { title: magazine.data!.title })}
            confirmLabel={t('common.delete')}
            loading={remove.isPending}
            onClose={close}
            onConfirm={() =>
              remove.mutate(id, {
                onSuccess: () => {
                  notifySuccess(t('magazine.deleted', { title: magazine.data!.title }));
                  navigate('/library');
                },
                onError: notifyError,
              })
            }
          />
        </Stack>
      )}
    </QueryState>
  );
}
