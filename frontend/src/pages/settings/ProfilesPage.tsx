import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Checkbox,
  Group,
  Modal,
  NumberInput,
  Radio,
  SimpleGrid,
  Stack,
  Table,
  TagsInput,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { IconArrowDown, IconArrowUp, IconEdit, IconPlus, IconTrash } from '@tabler/icons-react';
import { useState } from 'react';

import {
  useDeleteQualityProfile,
  useQualities,
  useQualityProfiles,
  useSaveQualityProfile,
} from '../../api/settings';
import type { Protocol, QualityProfile, QualityProfileItem } from '../../api/types';
import { ConfirmModal } from '../../components/ConfirmModal';
import { PageHeader } from '../../components/PageHeader';
import { QueryState } from '../../components/QueryState';
import { t } from '../../i18n';
import { notifyError, notifySuccess } from '../../notify';

interface EditorProps {
  profile: QualityProfile | null;
  defaultItems: QualityProfileItem[];
  qualityName: (id: string) => string;
  onClose: () => void;
}

function ProfileEditor({ profile, defaultItems, qualityName, onClose }: EditorProps) {
  const save = useSaveQualityProfile();
  const [name, setName] = useState(profile?.name ?? '');
  const [items, setItems] = useState<QualityProfileItem[]>(profile?.items ?? defaultItems);
  const [protocols, setProtocols] = useState<Protocol[]>(profile?.protocols ?? ['usenet', 'torrent']);
  const [mustContain, setMustContain] = useState<string[]>(profile?.mustContain ?? []);
  const [mustNotContain, setMustNotContain] = useState<string[]>(profile?.mustNotContain ?? []);
  const cutoff = items.find((i) => i.upgradeUntil)?.quality ?? '';

  const patch = (index: number, change: Partial<QualityProfileItem>) =>
    setItems((current) => current.map((item, i) => (i === index ? { ...item, ...change } : item)));
  const move = (index: number, delta: number) =>
    setItems((current) => {
      const next = [...current];
      const [item] = next.splice(index, 1);
      next.splice(index + delta, 0, item!);
      return next;
    });
  const setCutoff = (quality: string) =>
    setItems((current) => current.map((item) => ({ ...item, upgradeUntil: item.quality === quality })));

  const submit = () =>
    save.mutate(
      { id: profile?.id, name, items, protocols, mustContain, mustNotContain },
      {
        onSuccess: () => {
          notifySuccess(t('profiles.saved'));
          onClose();
        },
        onError: notifyError,
      },
    );

  return (
    <Modal opened onClose={onClose} size="lg" title={profile ? t('profiles.edit') : t('profiles.add')}>
      <Stack>
        <TextInput label={t('profiles.name')} withAsterisk value={name} onChange={(e) => setName(e.currentTarget.value)} />
        <Text size="sm" c="dimmed">
          {t('profiles.help')}
        </Text>
        <Radio.Group value={cutoff} onChange={setCutoff}>
          <Table verticalSpacing={4}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('profiles.column.quality')}</Table.Th>
                <Table.Th>{t('profiles.column.allowed')}</Table.Th>
                <Table.Th>{t('profiles.column.maxSize')}</Table.Th>
                <Table.Th>{t('profiles.column.cutoff')}</Table.Th>
                <Table.Th w={70} />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {items.map((item, index) => (
                <Table.Tr key={item.quality}>
                  <Table.Td>{qualityName(item.quality)}</Table.Td>
                  <Table.Td>
                    <Checkbox
                      aria-label={t('profiles.allow', { quality: qualityName(item.quality) })}
                      checked={item.allowed}
                      onChange={(e) => patch(index, { allowed: e.currentTarget.checked })}
                    />
                  </Table.Td>
                  <Table.Td>
                    <NumberInput
                      size="xs"
                      w={110}
                      min={1}
                      allowDecimal={false}
                      placeholder={t('profiles.noLimit')}
                      aria-label={t('profiles.maxSizeFor', { quality: qualityName(item.quality) })}
                      value={item.maxSizeMb ?? ''}
                      onChange={(v) => patch(index, { maxSizeMb: v === '' ? null : Number(v) })}
                    />
                  </Table.Td>
                  <Table.Td>
                    <Radio
                      value={item.quality}
                      disabled={!item.allowed}
                      aria-label={t('profiles.cutoffFor', { quality: qualityName(item.quality) })}
                    />
                  </Table.Td>
                  <Table.Td>
                    <Group gap={0} wrap="nowrap">
                      <ActionIcon
                        variant="subtle"
                        size="sm"
                        disabled={index === 0}
                        aria-label={t('profiles.moveUp', { quality: qualityName(item.quality) })}
                        onClick={() => move(index, -1)}
                      >
                        <IconArrowUp size={14} />
                      </ActionIcon>
                      <ActionIcon
                        variant="subtle"
                        size="sm"
                        disabled={index === items.length - 1}
                        aria-label={t('profiles.moveDown', { quality: qualityName(item.quality) })}
                        onClick={() => move(index, 1)}
                      >
                        <IconArrowDown size={14} />
                      </ActionIcon>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Radio.Group>
        <Checkbox.Group
          label={t('profiles.protocols')}
          value={protocols}
          onChange={(v) => setProtocols(v as Protocol[])}
        >
          <Group mt={4}>
            <Checkbox value="usenet" label={t('search.protocol.usenet')} />
            <Checkbox value="torrent" label={t('search.protocol.torrent')} />
          </Group>
        </Checkbox.Group>
        <TagsInput
          label={t('profiles.mustContain')}
          description={t('profiles.terms.hint')}
          value={mustContain}
          onChange={setMustContain}
        />
        <TagsInput
          label={t('profiles.mustNotContain')}
          description={t('profiles.terms.hint')}
          value={mustNotContain}
          onChange={setMustNotContain}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={submit} loading={save.isPending} disabled={!name.trim() || protocols.length === 0}>
            {t('common.save')}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

export function ProfilesPage() {
  const profiles = useQualityProfiles();
  const qualities = useQualities();
  const remove = useDeleteQualityProfile();
  const [editing, setEditing] = useState<QualityProfile | 'new' | null>(null);
  const [deleting, setDeleting] = useState<QualityProfile | null>(null);

  const qualityName = (id: string) => qualities.data?.find((q) => q.id === id)?.name ?? id;
  const defaultItems: QualityProfileItem[] = [...(qualities.data ?? [])]
    .reverse()
    .map((q) => ({ quality: q.id, allowed: true, maxSizeMb: null, upgradeUntil: false }));

  return (
    <Stack gap="lg" maw={1100}>
      <PageHeader title={t('nav.settings.profiles')}>
        <Button leftSection={<IconPlus size={16} />} onClick={() => setEditing('new')} disabled={!qualities.data}>
          {t('profiles.add')}
        </Button>
      </PageHeader>
      <QueryState isPending={profiles.isPending} error={profiles.error}>
        {() => (
          <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
            {profiles.data!.map((profile) => (
              <Card key={profile.id} withBorder padding="md">
                <Group justify="space-between" mb="sm">
                  <Title order={5}>{profile.name}</Title>
                  <Group gap={2}>
                    <ActionIcon
                      variant="subtle"
                      aria-label={t('profiles.editNamed', { name: profile.name })}
                      onClick={() => setEditing(profile)}
                    >
                      <IconEdit size={16} />
                    </ActionIcon>
                    <ActionIcon
                      variant="subtle"
                      color="red"
                      aria-label={t('profiles.deleteNamed', { name: profile.name })}
                      onClick={() => setDeleting(profile)}
                    >
                      <IconTrash size={16} />
                    </ActionIcon>
                  </Group>
                </Group>
                <Group gap={4}>
                  {profile.items
                    .filter((item) => item.allowed)
                    .map((item) => (
                      <Badge key={item.quality} variant={item.upgradeUntil ? 'filled' : 'light'}>
                        {qualityName(item.quality)}
                      </Badge>
                    ))}
                </Group>
              </Card>
            ))}
          </SimpleGrid>
        )}
      </QueryState>
      {editing && (
        <ProfileEditor
          profile={editing === 'new' ? null : editing}
          defaultItems={defaultItems}
          qualityName={qualityName}
          onClose={() => setEditing(null)}
        />
      )}
      <ConfirmModal
        opened={deleting !== null}
        title={t('profiles.delete.title')}
        message={t('profiles.delete.message', { name: deleting?.name ?? '' })}
        confirmLabel={t('common.delete')}
        loading={remove.isPending}
        onClose={() => setDeleting(null)}
        onConfirm={() =>
          deleting && remove.mutate(deleting.id, { onSuccess: () => setDeleting(null), onError: notifyError })
        }
      />
    </Stack>
  );
}
