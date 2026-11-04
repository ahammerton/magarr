import { Badge, Button, Card, Code, Group, ScrollArea, SegmentedControl, Stack, Table, Text, Tooltip } from '@mantine/core';
import { IconDownload, IconPlayerPause, IconPlayerPlay } from '@tabler/icons-react';
import { useEffect, useRef, useState } from 'react';

import { saveApiFile } from '../../api/client';
import { fetchLogs } from '../../api/systemPages';
import type { LogEntry } from '../../api/types';
import { PageHeader } from '../../components/PageHeader';
import { t } from '../../i18n';
import { notifyError } from '../../notify';

const KEEP = 1000; // entries shown
const POLL_MS = 2000;
const LEVEL_COLORS: Record<string, string> = { DEBUG: 'gray', INFO: 'blue', WARNING: 'orange', ERROR: 'red', CRITICAL: 'red' };

export function LogsPage() {
  const [level, setLevel] = useState('INFO');
  const [paused, setPaused] = useState(false);
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const lastId = useRef(0);

  useEffect(() => {
    if (paused) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const page = await fetchLogs(lastId.current, level);
        if (cancelled) return;
        lastId.current = page.lastId;
        setError(null);
        if (page.entries.length) setEntries((current) => [...current, ...page.entries].slice(-KEEP));
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    };
    void tick();
    const timer = setInterval(() => void tick(), POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [level, paused]);

  useEffect(() => {
    // Follow the tail, like `tail -f`.
    if (viewport.current) viewport.current.scrollTop = viewport.current.scrollHeight;
  }, [entries]);

  return (
    <Stack gap="lg">
      <PageHeader title={t('nav.system.logs')}>
        <SegmentedControl
          size="xs"
          value={level}
          onChange={(next) => {
            // A new level starts the list afresh.
            setEntries([]);
            lastId.current = 0;
            setLevel(next);
          }}
          data={(['DEBUG', 'INFO', 'WARNING', 'ERROR'] as const).map((l) => ({ value: l, label: t(`logs.level.${l}`) }))}
        />
        <Button
          variant="default"
          size="xs"
          leftSection={paused ? <IconPlayerPlay size={14} /> : <IconPlayerPause size={14} />}
          onClick={() => setPaused((p) => !p)}
        >
          {paused ? t('logs.resume') : t('logs.pause')}
        </Button>
        <Button
          variant="default"
          size="xs"
          leftSection={<IconDownload size={14} />}
          onClick={() => saveApiFile('/api/v1/system/logs/file', 'magarr.log').catch(notifyError)}
        >
          {t('logs.download')}
        </Button>
      </PageHeader>
      {error && (
        <Text c="red" size="sm">
          {error}
        </Text>
      )}
      <Card withBorder padding={0}>
        <ScrollArea h="calc(100vh - 220px)" viewportRef={viewport}>
          {entries.length === 0 ? (
            <Text c="dimmed" size="sm" p="md">
              {t('logs.empty')}
            </Text>
          ) : (
            <Table verticalSpacing={2} fz="xs" striped>
              <Table.Tbody>
                {entries.map((entry) => (
                  <Table.Tr key={entry.id} data-testid="log-row">
                    <Table.Td style={{ whiteSpace: 'nowrap' }} c="dimmed">
                      {new Date(entry.time).toLocaleTimeString()}
                    </Table.Td>
                    <Table.Td>
                      <Badge size="xs" variant="light" color={LEVEL_COLORS[entry.level] ?? 'gray'}>
                        {entry.level}
                      </Badge>
                    </Table.Td>
                    <Table.Td c="dimmed" style={{ whiteSpace: 'nowrap' }}>
                      {entry.logger}
                    </Table.Td>
                    <Table.Td style={{ overflowWrap: 'anywhere' }}>
                      <Group gap={6}>
                        <Text size="xs">{entry.message}</Text>
                        {Object.keys(entry.data).length > 0 && (
                          <Tooltip label={<Code block>{JSON.stringify(entry.data, null, 2)}</Code>} multiline maw={500}>
                            <Code fz={10} style={{ cursor: 'help' }}>
                              {Object.keys(entry.data).join(', ')}
                            </Code>
                          </Tooltip>
                        )}
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
        </ScrollArea>
      </Card>
    </Stack>
  );
}
