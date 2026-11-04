import { Button, Group, Modal, NumberInput, SegmentedControl, Stack, Switch, Tabs, Text, TextInput } from '@mantine/core';
import { useForm } from '@mantine/form';

import { useCreateIssue, useGenerateIssues, useUpdateIssue, useUpdateMagazine } from '../../api/magazines';
import { useQualityProfiles, useRootFolders } from '../../api/settings';
import type { Issue, Magazine } from '../../api/types';
import { DetailsFields, SettingsFields } from '../../components/MagazineFields';
import { type MagazineFormValues, toMagazineInput, validateTitle } from '../../components/magazineForm';
import { startOfThisMonth } from '../../format';
import { t } from '../../i18n';
import { notifyError, notifySuccess } from '../../notify';

interface ModalProps {
  opened: boolean;
  onClose: () => void;
}

function magazineValues(magazine: Magazine): MagazineFormValues {
  return {
    title: magazine.title,
    alternateTitles: magazine.alternateTitles,
    publisher: magazine.publisher ?? '',
    language: magazine.language,
    category: magazine.category ?? '',
    frequency: magazine.frequency,
    firstIssueYear: magazine.firstIssueYear ?? '',
    tags: magazine.tags,
    qualityProfileId: String(magazine.qualityProfileId),
    rootFolderId: String(magazine.rootFolderId),
    monitored: magazine.monitored,
    posterUrl: magazine.posterUrl ?? '',
    searchCutoff: magazine.searchCutoff ?? '',
    grabNewSpecials: magazine.grabNewSpecials,
    issueNamingTemplate: magazine.issueNamingTemplate ?? '',
    notes: magazine.notes ?? '',
  };
}

export function EditMagazineModal({ magazine, opened, onClose }: ModalProps & { magazine: Magazine }) {
  const update = useUpdateMagazine(magazine.id);
  const rootFolders = useRootFolders();
  const profiles = useQualityProfiles();
  const form = useForm<MagazineFormValues>({
    initialValues: magazineValues(magazine),
    validate: { title: validateTitle },
  });

  const submit = form.onSubmit((values) =>
    update.mutate(toMagazineInput(values), {
      onSuccess: () => {
        notifySuccess(t('magazine.saved'));
        onClose();
      },
      onError: notifyError,
    }),
  );

  return (
    <Modal opened={opened} onClose={onClose} title={t('magazine.edit')} size="lg">
      <form onSubmit={submit}>
        <Tabs defaultValue="details">
          <Tabs.List>
            <Tabs.Tab value="details">{t('add.step.details')}</Tabs.Tab>
            <Tabs.Tab value="settings">{t('add.step.settings')}</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="details">
            <Stack mt="md">
              <DetailsFields form={form} />
            </Stack>
          </Tabs.Panel>
          <Tabs.Panel value="settings">
            <Stack mt="md">
              <SettingsFields
                form={form}
                showNamingTemplate
                rootFolders={(rootFolders.data ?? []).map((r) => ({ value: String(r.id), label: r.path }))}
                profiles={(profiles.data ?? []).map((p) => ({ value: String(p.id), label: p.name }))}
              />
            </Stack>
          </Tabs.Panel>
        </Tabs>
        <Group justify="flex-end" mt="lg">
          <Button variant="default" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" loading={update.isPending}>
            {t('common.save')}
          </Button>
        </Group>
      </form>
    </Modal>
  );
}

type Numbering = 'date' | 'number';

/** One past the highest plain issue number, so a numbered run continues the sequence. */
function nextIssueNumber(issues: Issue[]): number {
  const numbers = issues.map((i) => i.issueNumber).filter((n) => /^\d+$/.test(n)).map(Number);
  return numbers.length ? Math.max(...numbers) + 1 : 1;
}

export function GenerateIssuesModal({
  magazine,
  issues,
  opened,
  onClose,
}: ModalProps & { magazine: Magazine; issues: Issue[] }) {
  const generate = useGenerateIssues(magazine.id);
  const adHoc = magazine.frequency === 'ad-hoc';
  const hasNumbers = issues.some((i) => /^\d+$/.test(i.issueNumber));
  const form = useForm({
    initialValues: {
      // Continue the way the magazine is already numbered; ad-hoc can only be numbered.
      numbering: (adHoc || hasNumbers ? 'number' : 'date') as Numbering,
      firstNumber: nextIssueNumber(issues) as number | string,
      start: adHoc ? '' : startOfThisMonth(),
      count: 12 as number | string,
      monitored: false,
    },
    validate: {
      start: (v, values) => {
        if (adHoc || (values.numbering === 'number' && v === '')) return null; // optional
        return /^\d{4}-\d{2}-\d{2}$/.test(v) ? null : t('generate.validation.start');
      },
      firstNumber: (v, values) =>
        values.numbering === 'date' || (v !== '' && Number(v) >= 0) ? null : t('generate.validation.number'),
      count: (v) => (Number(v) >= 1 && Number(v) <= 520 ? null : t('generate.validation.count')),
    },
  });
  const numbered = form.values.numbering === 'number';

  const submit = form.onSubmit((values) =>
    generate.mutate(
      {
        start: adHoc || values.start === '' ? null : values.start,
        count: Number(values.count),
        monitored: values.monitored,
        firstNumber: numbered ? Number(values.firstNumber) : null,
      },
      {
        onSuccess: (result) => {
          notifySuccess(t('generate.done', { created: result.created.length, skipped: result.skipped }));
          onClose();
        },
        onError: notifyError,
      },
    ),
  );

  const first = Number(form.values.firstNumber) || 0;
  const count = Math.max(Number(form.values.count) || 1, 1);
  return (
    <Modal opened={opened} onClose={onClose} title={t('generate.title')}>
      <form onSubmit={submit}>
        <Stack>
          <SegmentedControl
            fullWidth
            data={[
              { value: 'date', label: t('generate.numbering.date'), disabled: adHoc },
              { value: 'number', label: t('generate.numbering.number') },
            ]}
            {...form.getInputProps('numbering')}
          />
          {adHoc && (
            <Text size="sm" c="dimmed">
              {t('generate.adHoc')}
            </Text>
          )}
          {numbered && (
            <NumberInput
              label={t('generate.firstNumber')}
              description={t('generate.firstNumber.hint', { first, last: first + count - 1 })}
              min={0}
              allowDecimal={false}
              {...form.getInputProps('firstNumber')}
            />
          )}
          {!adHoc && (
            <TextInput
              type="date"
              label={numbered ? t('generate.start.optional') : t('generate.start')}
              description={
                numbered
                  ? t('generate.start.optional.hint', { frequency: t(`frequency.${magazine.frequency}`) })
                  : t('generate.start.hint', { frequency: t(`frequency.${magazine.frequency}`) })
              }
              {...form.getInputProps('start')}
            />
          )}
          <NumberInput label={t('generate.count')} min={1} max={520} allowDecimal={false} {...form.getInputProps('count')} />
          <Switch label={t('generate.monitored')} {...form.getInputProps('monitored', { type: 'checkbox' })} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" loading={generate.isPending}>
              {t('generate.submit')}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

interface IssueModalProps extends ModalProps {
  magazineId: number;
  /** Present when editing. */
  issue?: Issue;
}

export function IssueModal({ magazineId, issue, opened, onClose }: IssueModalProps) {
  const create = useCreateIssue(magazineId);
  const update = useUpdateIssue();
  const form = useForm({
    initialValues: {
      issueNumber: issue?.issueNumber ?? '',
      title: issue?.title ?? '',
      publishDate: issue?.publishDate ?? '',
      monitored: issue?.monitored ?? true,
    },
    validate: { issueNumber: (v) => (v.trim() ? null : t('issue.validation.number')) },
  });

  const submit = form.onSubmit((values) => {
    const body = {
      issueNumber: values.issueNumber.trim(),
      title: values.title.trim() || null,
      publishDate: values.publishDate || null,
      monitored: values.monitored,
    };
    const callbacks = {
      onSuccess: () => {
        notifySuccess(t('issue.saved'));
        onClose();
      },
      onError: notifyError,
    };
    if (issue) update.mutate({ id: issue.id, ...body }, callbacks);
    else create.mutate(body, callbacks);
  });

  return (
    <Modal opened={opened} onClose={onClose} title={issue ? t('issue.edit') : t('issue.add')}>
      <form onSubmit={submit}>
        <Stack>
          <TextInput
            label={t('issue.field.number')}
            description={t('issue.field.number.hint')}
            withAsterisk
            data-autofocus
            {...form.getInputProps('issueNumber')}
          />
          <TextInput label={t('issue.field.title')} {...form.getInputProps('title')} />
          <TextInput type="date" label={t('issue.field.publishDate')} {...form.getInputProps('publishDate')} />
          <Switch label={t('common.monitored')} {...form.getInputProps('monitored', { type: 'checkbox' })} />
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" loading={create.isPending || update.isPending}>
              {t('common.save')}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}
