import { Alert, Button, Card, Group, NumberInput, Stack, Switch, Table, Text, Title } from '@mantine/core';
import { useForm } from '@mantine/form';
import { IconPlayerPause } from '@tabler/icons-react';

import { useAutomation, useSaveAutomation } from '../../api/automation';
import type { Automation, AutomationSettings } from '../../api/types';
import { PageHeader } from '../../components/PageHeader';
import { QueryState } from '../../components/QueryState';
import { t } from '../../i18n';
import { notifyError, notifySuccess } from '../../notify';

// Matches the server's limits: indexers ban clients that poll faster.
const MIN_RSS = 10;
const MIN_BACKLOG = 15;

function settingsOf(a: Automation): AutomationSettings {
  return {
    monitoringEnabled: a.monitoringEnabled,
    rssIntervalMinutes: a.rssIntervalMinutes,
    backlogIntervalMinutes: a.backlogIntervalMinutes,
    backlogBatchSize: a.backlogBatchSize,
    expectedLookaheadDays: a.expectedLookaheadDays,
  };
}

const interval = (min: number) => (value: number) =>
  value === 0 || value >= min ? null : t('automation.validation.interval', { min });

function AutomationForm({ initial }: { initial: AutomationSettings }) {
  const save = useSaveAutomation();
  const form = useForm<AutomationSettings>({
    initialValues: initial,
    validate: {
      rssIntervalMinutes: interval(MIN_RSS),
      backlogIntervalMinutes: interval(MIN_BACKLOG),
    },
  });
  const number = (key: keyof AutomationSettings) => {
    const props = form.getInputProps(key);
    return { ...props, onChange: (v: string | number) => form.setFieldValue(key, v === '' ? 0 : Number(v)) };
  };
  return (
    <form
      onSubmit={form.onSubmit((values) =>
        save.mutate(values, {
          onSuccess: (saved) => {
            form.resetDirty(settingsOf(saved));
            notifySuccess(t('automation.saved'));
          },
          onError: notifyError,
        }),
      )}
    >
      <Stack>
        <Switch
          label={t('automation.monitoring')}
          description={t('automation.monitoring.hint')}
          {...form.getInputProps('monitoringEnabled', { type: 'checkbox' })}
        />
        <Group grow align="flex-start">
          <NumberInput
            label={t('automation.rssInterval')}
            description={t('automation.rssInterval.hint', { min: MIN_RSS })}
            min={0}
            max={1440}
            allowDecimal={false}
            suffix={` ${t('automation.minutes')}`}
            {...number('rssIntervalMinutes')}
          />
          <NumberInput
            label={t('automation.backlogInterval')}
            description={t('automation.backlogInterval.hint', { min: MIN_BACKLOG })}
            min={0}
            max={10080}
            allowDecimal={false}
            suffix={` ${t('automation.minutes')}`}
            {...number('backlogIntervalMinutes')}
          />
        </Group>
        <Group grow align="flex-start">
          <NumberInput
            label={t('automation.batchSize')}
            description={t('automation.batchSize.hint')}
            min={1}
            max={100}
            allowDecimal={false}
            {...number('backlogBatchSize')}
          />
          <NumberInput
            label={t('automation.lookahead')}
            description={t('automation.lookahead.hint')}
            min={0}
            max={365}
            allowDecimal={false}
            suffix={` ${t('automation.days')}`}
            {...number('expectedLookaheadDays')}
          />
        </Group>
        <Group justify="flex-end">
          <Button type="submit" loading={save.isPending} disabled={!form.isDirty()}>
            {t('common.save')}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

function Jobs({ automation }: { automation: Automation }) {
  return (
    <Table verticalSpacing="xs">
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{t('automation.job')}</Table.Th>
          <Table.Th>{t('automation.lastRun')}</Table.Th>
          <Table.Th>{t('automation.lastResult')}</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {automation.jobs.map((job) => (
          <Table.Tr key={job.name} data-testid="automation-job">
            <Table.Td>{t(`automation.job.${job.name}`)}</Table.Td>
            <Table.Td>{job.lastRun ? new Date(job.lastRun).toLocaleString() : t('automation.notYet')}</Table.Td>
            <Table.Td>{job.lastResult ?? '—'}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

export function AutomationPage() {
  const automation = useAutomation();
  return (
    <Stack gap="lg" maw={900}>
      <PageHeader title={t('nav.settings.automation')} />
      <QueryState isPending={automation.isPending} error={automation.error}>
        {() => (
          <>
            {!automation.data!.monitoringEnabled && (
              <Alert color="orange" icon={<IconPlayerPause />} title={t('automation.paused.title')}>
                {t('automation.paused.body')}
              </Alert>
            )}
            <Card withBorder padding="lg">
              <Title order={4} mb="xs">
                {t('automation.title')}
              </Title>
              <Text size="sm" c="dimmed" mb="md">
                {t('automation.help')}
              </Text>
              <AutomationForm initial={settingsOf(automation.data!)} />
            </Card>
            <Card withBorder padding="lg">
              <Title order={4} mb="xs">
                {t('automation.jobs')}
              </Title>
              <Text size="sm" c="dimmed" mb="md">
                {t('automation.jobs.help')}
              </Text>
              <Jobs automation={automation.data!} />
            </Card>
          </>
        )}
      </QueryState>
    </Stack>
  );
}
