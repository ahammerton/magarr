import { Alert, Button, Card, Code, FileButton, Group, List, Stack, Switch, Table, Text, Textarea } from '@mantine/core';
import { IconCheck, IconUpload } from '@tabler/icons-react';
import { useState } from 'react';

import { useCsvImport } from '../../api/magazines';
import type { CsvImportResult } from '../../api/types';
import { PageHeader } from '../../components/PageHeader';
import { t } from '../../i18n';
import { notifyError } from '../../notify';

const EXAMPLE = 'magazine,issue,date,issue_title\nNational Geographic,2024-05,2024-05-01,The Ocean Issue';

function ResultSummary({ result }: { result: CsvImportResult }) {
  return (
    <Stack>
      <Alert color={result.errors.length ? 'orange' : 'teal'} icon={<IconCheck />} title={t('csv.result.title')}>
        <List size="sm">
          <List.Item>{t('csv.result.created', { count: result.issuesCreated })}</List.Item>
          <List.Item>{t('csv.result.updated', { count: result.issuesUpdated })}</List.Item>
          <List.Item>{t('csv.result.unchanged', { count: result.issuesUnchanged })}</List.Item>
          {result.magazinesCreated.length > 0 && (
            <List.Item>
              {t('csv.result.magazines', { titles: result.magazinesCreated.join(', ') })}
            </List.Item>
          )}
        </List>
      </Alert>
      {result.errors.length > 0 && (
        <Table withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th w={80}>{t('csv.error.row')}</Table.Th>
              <Table.Th>{t('csv.error.message')}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {result.errors.map((error) => (
              <Table.Tr key={error.row}>
                <Table.Td>{error.row}</Table.Td>
                <Table.Td>{error.message}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}

export function ImportCsvPage() {
  const [csv, setCsv] = useState('');
  const [createMissing, setCreateMissing] = useState(false);
  const [monitored, setMonitored] = useState(false);
  const importCsv = useCsvImport();

  const loadFile = (file: File | null) => {
    if (file) void file.text().then(setCsv);
  };

  return (
    <Stack gap="lg" maw={900}>
      <PageHeader title={t('csv.title')} />
      <Card withBorder padding="lg">
        <Stack>
          <Text size="sm">{t('csv.help')}</Text>
          <Code block>{EXAMPLE}</Code>
          <Textarea
            label={t('csv.input')}
            autosize
            minRows={6}
            maxRows={20}
            styles={{ input: { fontFamily: 'var(--mantine-font-family-monospace)' } }}
            value={csv}
            onChange={(event) => setCsv(event.currentTarget.value)}
          />
          <Group>
            <FileButton onChange={loadFile} accept=".csv,text/csv,text/plain">
              {(props) => (
                <Button variant="default" leftSection={<IconUpload size={16} />} {...props}>
                  {t('csv.chooseFile')}
                </Button>
              )}
            </FileButton>
          </Group>
          <Switch
            label={t('csv.createMissing')}
            checked={createMissing}
            onChange={(event) => setCreateMissing(event.currentTarget.checked)}
          />
          <Switch
            label={t('csv.monitored')}
            checked={monitored}
            onChange={(event) => setMonitored(event.currentTarget.checked)}
          />
          <Group justify="flex-end">
            <Button
              disabled={!csv.trim()}
              loading={importCsv.isPending}
              onClick={() => importCsv.mutate({ csv, createMissing, monitored }, { onError: notifyError })}
            >
              {t('csv.submit')}
            </Button>
          </Group>
        </Stack>
      </Card>
      {importCsv.data && <ResultSummary result={importCsv.data} />}
    </Stack>
  );
}
