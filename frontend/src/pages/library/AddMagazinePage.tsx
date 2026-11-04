import { Alert, Anchor, Button, Card, Group, Stack, Stepper, Table, Text } from '@mantine/core';
import { useForm } from '@mantine/form';
import { IconAlertTriangle } from '@tabler/icons-react';
import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { useCreateMagazine } from '../../api/magazines';
import { useQualityProfiles, useRootFolders } from '../../api/settings';
import { DetailsFields, SettingsFields } from '../../components/MagazineFields';
import {
  EMPTY_MAGAZINE,
  type MagazineFormValues,
  toMagazineInput,
  validateTitle,
} from '../../components/magazineForm';
import { PageHeader } from '../../components/PageHeader';
import { t } from '../../i18n';
import { notifyError, notifySuccess } from '../../notify';

export function AddMagazinePage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const rootFolders = useRootFolders();
  const profiles = useQualityProfiles();
  const create = useCreateMagazine();
  const form = useForm<MagazineFormValues>({
    initialValues: EMPTY_MAGAZINE,
    validate: { title: validateTitle },
  });

  // Preselect the default root folder and first profile once they load.
  const { setFieldValue } = form;
  const { rootFolderId, qualityProfileId } = form.values;
  useEffect(() => {
    const root = rootFolders.data?.find((r) => r.isDefault) ?? rootFolders.data?.[0];
    if (root && !rootFolderId) setFieldValue('rootFolderId', String(root.id));
  }, [rootFolders.data, rootFolderId, setFieldValue]);
  useEffect(() => {
    const profile = profiles.data?.[0];
    if (profile && !qualityProfileId) setFieldValue('qualityProfileId', String(profile.id));
  }, [profiles.data, qualityProfileId, setFieldValue]);

  const noRootFolders = rootFolders.data?.length === 0;
  const rootOptions = (rootFolders.data ?? []).map((r) => ({ value: String(r.id), label: r.path }));
  const profileOptions = (profiles.data ?? []).map((p) => ({ value: String(p.id), label: p.name }));

  const next = () => {
    if (step === 0 && form.validate().hasErrors) return;
    setStep((s) => Math.min(s + 1, 2));
  };

  const submit = () =>
    create.mutate(toMagazineInput(form.values), {
      onSuccess: (magazine) => {
        notifySuccess(t('add.created', { title: magazine.title }));
        navigate(`/magazine/${magazine.id}`);
      },
      onError: notifyError,
    });

  const values = form.values;
  const summary: [string, string][] = [
    [t('magazine.field.title'), values.title],
    [t('magazine.field.alternateTitles'), values.alternateTitles.join(', ') || '—'],
    [t('magazine.field.publisher'), values.publisher || '—'],
    [t('magazine.field.category'), values.category || '—'],
    [t('magazine.field.frequency'), t(`frequency.${values.frequency}`)],
    [t('magazine.field.firstIssueYear'), String(values.firstIssueYear || '—')],
    [t('magazine.field.rootFolder'), rootOptions.find((o) => o.value === values.rootFolderId)?.label ?? '—'],
    [t('magazine.field.qualityProfile'), profileOptions.find((o) => o.value === values.qualityProfileId)?.label ?? '—'],
    [t('magazine.field.tags'), values.tags.join(', ') || '—'],
    [t('magazine.field.monitored'), values.monitored ? t('common.yes') : t('common.no')],
  ];

  return (
    <Stack gap="lg" maw={720}>
      <PageHeader title={t('add.title')} />
      {noRootFolders && (
        <Alert color="orange" icon={<IconAlertTriangle />} title={t('add.noRoot.title')}>
          {t('add.noRoot.body')}{' '}
          <Anchor component={Link} to="/settings/mediamanagement">
            {t('nav.settings.media')}
          </Anchor>
        </Alert>
      )}
      <Card withBorder padding="lg">
        <Stepper active={step} onStepClick={(s) => s < step && setStep(s)} size="sm">
          <Stepper.Step label={t('add.step.details')}>
            <Stack mt="md">
              <DetailsFields form={form} />
            </Stack>
          </Stepper.Step>
          <Stepper.Step label={t('add.step.settings')}>
            <Stack mt="md">
              <SettingsFields form={form} rootFolders={rootOptions} profiles={profileOptions} />
            </Stack>
          </Stepper.Step>
          <Stepper.Step label={t('add.step.review')}>
            <Table mt="md" variant="vertical" withTableBorder={false}>
              <Table.Tbody>
                {summary.map(([label, value]) => (
                  <Table.Tr key={label}>
                    <Table.Th w={200}>{label}</Table.Th>
                    <Table.Td>
                      <Text size="sm">{value}</Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Stepper.Step>
        </Stepper>
        <Group justify="space-between" mt="xl">
          <Button variant="default" disabled={step === 0} onClick={() => setStep((s) => s - 1)}>
            {t('common.back')}
          </Button>
          {step < 2 ? (
            <Button onClick={next}>{t('common.next')}</Button>
          ) : (
            <Button onClick={submit} loading={create.isPending} disabled={noRootFolders}>
              {t('add.submit')}
            </Button>
          )}
        </Group>
      </Card>
    </Stack>
  );
}
