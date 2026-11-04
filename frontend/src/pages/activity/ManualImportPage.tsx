import { Alert, Button, Checkbox, Code, Group, SegmentedControl, Select, Stack, Table, Text, TextInput } from '@mantine/core';
import { IconAlertTriangle, IconFolderSearch } from '@tabler/icons-react';
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { useManualImport, useManualImportScan } from '../../api/activity';
import { useIssues, useMagazines } from '../../api/magazines';
import { useQualities } from '../../api/settings';
import type { ManualImportItem } from '../../api/types';
import { PageHeader } from '../../components/PageHeader';
import { formatBytes } from '../../format';
import { t } from '../../i18n';
import { notifyError, notifySuccess } from '../../notify';

interface Row {
  item: ManualImportItem;
  selected: boolean;
  magazineId: string | null;
  issueId: string | null;
  quality: string;
  result?: { ok: boolean; text: string };
}

function IssueSelect({ magazineId, value, onChange, label }: { magazineId: string | null; value: string | null; onChange: (v: string | null) => void; label: string }) {
  const issues = useIssues(Number(magazineId), { enabled: magazineId !== null });
  const options = magazineId
    ? (issues.data ?? []).map((i) => ({ value: String(i.id), label: i.file ? `${i.issueNumber} (${t('status.issue.downloaded')})` : i.issueNumber }))
    : [];
  return <Select aria-label={label} placeholder="—" data={options} value={value} onChange={onChange} searchable disabled={!magazineId} w={170} />;
}

function toRows(items: ManualImportItem[]): Row[] {
  return items.map((item) => ({
    item,
    // Preselect files Magarr is confident about.
    selected: item.issueId !== null && item.warnings.length === 0,
    magazineId: item.magazineId === null ? null : String(item.magazineId),
    issueId: item.issueId === null ? null : String(item.issueId),
    quality: item.quality,
  }));
}

export function ManualImportPage() {
  const [params] = useSearchParams();
  const downloadId = params.get('downloadId') ? Number(params.get('downloadId')) : undefined;
  const [path, setPath] = useState('');
  const [mode, setMode] = useState<'move' | 'copy'>('move');
  const [rows, setRows] = useState<Row[]>([]);
  const scan = useManualImportScan();
  const run = useManualImport();
  const magazines = useMagazines();
  const qualities = useQualities();

  const load = (source: { path?: string; downloadId?: number }) =>
    scan.mutate(source, { onSuccess: (result) => setRows(toRows(result.items)), onError: notifyError });

  const { mutate: scanNow } = scan;
  useEffect(() => {
    if (downloadId !== undefined) {
      scanNow({ downloadId }, { onSuccess: (result) => setRows(toRows(result.items)), onError: notifyError });
    }
  }, [downloadId, scanNow]);

  const update = (index: number, change: Partial<Row>) =>
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...change } : row)));
  const chosen = useMemo(() => rows.filter((r) => r.selected && r.issueId), [rows]);

  const submit = () =>
    run.mutate(
      {
        downloadId: downloadId ?? null,
        mode: downloadId !== undefined ? null : mode,
        files: chosen.map((r) => ({ path: r.item.path, issueId: Number(r.issueId), quality: r.quality })),
      },
      {
        onSuccess: (outcomes) => {
          const byPath = new Map(outcomes.map((o) => [o.path, o]));
          setRows((current) =>
            current.map((row) => {
              const outcome = byPath.get(row.item.path);
              if (!outcome) return row;
              return {
                ...row,
                selected: false,
                result: outcome.error
                  ? { ok: false, text: outcome.error }
                  : { ok: true, text: t('manual.importedTo', { path: outcome.importedTo ?? '' }) },
              };
            }),
          );
          const ok = outcomes.filter((o) => !o.error).length;
          notifySuccess(t('manual.done', { ok, failed: outcomes.length - ok }));
        },
        onError: notifyError,
      },
    );

  const magazineOptions = (magazines.data ?? []).map((m) => ({ value: String(m.id), label: m.title }));
  const qualityOptions = (qualities.data ?? []).map((q) => ({ value: q.id, label: q.name }));

  return (
    <Stack gap="lg">
      <PageHeader title={t('nav.activity.import')} />
      {downloadId === undefined ? (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (path.trim()) load({ path: path.trim() });
          }}
        >
          <Group align="flex-end">
            <TextInput
              label={t('manual.path')}
              description={t('manual.path.hint')}
              placeholder="/downloads/magazines"
              value={path}
              onChange={(e) => setPath(e.currentTarget.value)}
              style={{ flex: 1 }}
            />
            <Button type="submit" leftSection={<IconFolderSearch size={16} />} loading={scan.isPending} disabled={!path.trim()}>
              {t('manual.scan')}
            </Button>
          </Group>
        </form>
      ) : (
        scan.data && <Code>{scan.data.folder}</Code>
      )}
      {scan.isSuccess && rows.length === 0 && <Text c="dimmed">{t('manual.empty')}</Text>}
      {rows.length > 0 && (
        <Stack>
          <Table.ScrollContainer minWidth={1000}>
            <Table verticalSpacing="xs">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th w={36} />
                  <Table.Th>{t('manual.column.file')}</Table.Th>
                  <Table.Th>{t('manual.column.magazine')}</Table.Th>
                  <Table.Th>{t('queue.column.issue')}</Table.Th>
                  <Table.Th>{t('search.column.quality')}</Table.Th>
                  <Table.Th ta="right">{t('search.column.size')}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {rows.map((row, index) => (
                  <Table.Tr key={row.item.path} data-testid="manual-row">
                    <Table.Td>
                      <Checkbox
                        aria-label={t('manual.select', { file: row.item.relativePath })}
                        checked={row.selected}
                        disabled={!row.issueId || row.result?.ok}
                        onChange={(e) => update(index, { selected: e.currentTarget.checked })}
                      />
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm" ff="monospace" style={{ overflowWrap: 'anywhere' }}>
                        {row.item.relativePath}
                      </Text>
                      {row.result ? (
                        <Text size="xs" c={row.result.ok ? 'teal' : 'red'}>
                          {row.result.text}
                        </Text>
                      ) : (
                        row.item.warnings.map((w) => (
                          <Text key={w} size="xs" c="orange">
                            {w}
                          </Text>
                        ))
                      )}
                    </Table.Td>
                    <Table.Td>
                      <Select
                        aria-label={t('manual.magazineFor', { file: row.item.relativePath })}
                        placeholder="—"
                        data={magazineOptions}
                        value={row.magazineId}
                        onChange={(value) => update(index, { magazineId: value, issueId: null, selected: false })}
                        searchable
                        w={220}
                      />
                    </Table.Td>
                    <Table.Td>
                      <IssueSelect
                        label={t('manual.issueFor', { file: row.item.relativePath })}
                        magazineId={row.magazineId}
                        value={row.issueId}
                        onChange={(value) => update(index, { issueId: value, selected: value !== null })}
                      />
                    </Table.Td>
                    <Table.Td>
                      <Select
                        aria-label={t('manual.qualityFor', { file: row.item.relativePath })}
                        data={qualityOptions}
                        value={row.quality}
                        allowDeselect={false}
                        onChange={(value) => value && update(index, { quality: value })}
                        w={150}
                      />
                    </Table.Td>
                    <Table.Td ta="right" style={{ whiteSpace: 'nowrap' }}>
                      {formatBytes(row.item.size)}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          {chosen.some((r) => r.item.warnings.length > 0) && (
            <Alert color="orange" icon={<IconAlertTriangle />}>
              {t('manual.warningsSelected')}
            </Alert>
          )}
          <Group justify="flex-end">
            {downloadId === undefined && (
              <SegmentedControl
                value={mode}
                onChange={(v) => setMode(v as 'move' | 'copy')}
                data={[
                  { value: 'move', label: t('manual.mode.move') },
                  { value: 'copy', label: t('manual.mode.copy') },
                ]}
              />
            )}
            <Button onClick={submit} loading={run.isPending} disabled={chosen.length === 0}>
              {t('manual.import', { count: chosen.length })}
            </Button>
          </Group>
        </Stack>
      )}
    </Stack>
  );
}
