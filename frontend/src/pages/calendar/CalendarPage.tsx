import { ActionIcon, Anchor, Badge, Box, Button, Group, Paper, SimpleGrid, Stack, Switch, Text, Title } from '@mantine/core';
import { IconChevronLeft, IconChevronRight } from '@tabler/icons-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { useCalendar } from '../../api/automation';
import type { IssueStatus, MagazineIssue } from '../../api/types';
import { PageHeader } from '../../components/PageHeader';
import { QueryState } from '../../components/QueryState';
import { t } from '../../i18n';

const COLORS: Record<IssueStatus, string> = {
  downloaded: 'teal',
  wanted: 'orange',
  missing: 'gray',
  ignored: 'dark',
};

/** Local YYYY-MM-DD (toISOString would shift the date across time zones). */
function isoDate(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Monday-first weeks covering the whole month. */
function monthGrid(year: number, month: number): Date[] {
  const first = new Date(year, month, 1);
  const start = new Date(year, month, 1 - ((first.getDay() + 6) % 7));
  const last = new Date(year, month + 1, 0);
  const days: Date[] = [];
  for (let d = start; d <= last || days.length % 7 !== 0; d = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1)) {
    days.push(d);
  }
  return days;
}

const WEEKDAYS = Array.from({ length: 7 }, (_, i) =>
  new Date(2024, 0, 1 + i).toLocaleDateString(undefined, { weekday: 'short' }),
); // 1 Jan 2024 was a Monday

function IssueChip({ issue }: { issue: MagazineIssue }) {
  const label = `${issue.magazineTitle} · ${issue.issueNumber}`;
  return (
    <Badge
      component={Link}
      to={`/magazine/${issue.magazineId}`}
      color={COLORS[issue.status]}
      variant={issue.status === 'downloaded' ? 'filled' : 'light'}
      radius="sm"
      fullWidth
      title={`${label} (${t(`status.issue.${issue.status}`)})`}
      styles={{ root: { cursor: 'pointer', textTransform: 'none', justifyContent: 'flex-start' } }}
      data-testid="calendar-issue"
    >
      {label}
    </Badge>
  );
}

export function CalendarPage() {
  const today = new Date();
  const [cursor, setCursor] = useState({ year: today.getFullYear(), month: today.getMonth() });
  const [unmonitored, setUnmonitored] = useState(false);
  const days = useMemo(() => monthGrid(cursor.year, cursor.month), [cursor]);
  const start = isoDate(days[0]!);
  const end = isoDate(days[days.length - 1]!);
  const { data, isPending, error } = useCalendar(start, end, unmonitored);

  const byDay = useMemo(() => {
    const map = new Map<string, MagazineIssue[]>();
    for (const issue of data ?? []) {
      if (!issue.publishDate) continue;
      map.set(issue.publishDate, [...(map.get(issue.publishDate) ?? []), issue]);
    }
    return map;
  }, [data]);

  const move = (delta: number) =>
    setCursor(({ year, month }) => {
      const d = new Date(year, month + delta, 1);
      return { year: d.getFullYear(), month: d.getMonth() };
    });
  const title = new Date(cursor.year, cursor.month, 1).toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
  const todayIso = isoDate(today);
  const inMonth = days.filter((d) => d.getMonth() === cursor.month);

  return (
    <Stack gap="lg">
      <PageHeader title={t('nav.calendar')}>
        <Switch
          label={t('calendar.unmonitored')}
          checked={unmonitored}
          onChange={(e) => setUnmonitored(e.currentTarget.checked)}
        />
      </PageHeader>
      <Group justify="space-between">
        <Group gap="xs">
          <ActionIcon variant="default" aria-label={t('calendar.previous')} onClick={() => move(-1)}>
            <IconChevronLeft size={16} />
          </ActionIcon>
          <ActionIcon variant="default" aria-label={t('calendar.next')} onClick={() => move(1)}>
            <IconChevronRight size={16} />
          </ActionIcon>
          <Button
            variant="default"
            size="xs"
            onClick={() => setCursor({ year: today.getFullYear(), month: today.getMonth() })}
          >
            {t('calendar.today')}
          </Button>
        </Group>
        <Title order={3}>{title}</Title>
      </Group>
      <QueryState isPending={isPending} error={error}>
        {() => (
          <>
            {/* Month grid on wider screens. */}
            <Box visibleFrom="sm">
              <SimpleGrid cols={7} spacing={4} verticalSpacing={4}>
                {WEEKDAYS.map((day) => (
                  <Text key={day} size="xs" c="dimmed" ta="center" fw={600}>
                    {day}
                  </Text>
                ))}
                {days.map((day) => {
                  const iso = isoDate(day);
                  const issues = byDay.get(iso) ?? [];
                  return (
                    <Paper
                      key={iso}
                      withBorder
                      p={4}
                      mih={96}
                      opacity={day.getMonth() === cursor.month ? 1 : 0.45}
                      style={iso === todayIso ? { borderColor: 'var(--mantine-primary-color-filled)' } : undefined}
                      data-testid={`calendar-day-${iso}`}
                    >
                      <Text size="xs" fw={iso === todayIso ? 700 : 400} mb={2}>
                        {day.getDate()}
                      </Text>
                      <Stack gap={2}>
                        {issues.map((issue) => (
                          <IssueChip key={issue.id} issue={issue} />
                        ))}
                      </Stack>
                    </Paper>
                  );
                })}
              </SimpleGrid>
            </Box>
            {/* Day-by-day list on phones. */}
            <Stack hiddenFrom="sm" gap="sm">
              {inMonth.every((d) => !byDay.has(isoDate(d))) ? (
                <Text c="dimmed">{t('calendar.empty')}</Text>
              ) : (
                inMonth
                  .filter((d) => byDay.has(isoDate(d)))
                  .map((day) => (
                    <Stack key={isoDate(day)} gap={4}>
                      <Text size="sm" fw={600}>
                        {day.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })}
                      </Text>
                      {byDay.get(isoDate(day))!.map((issue) => (
                        <Anchor key={issue.id} component={Link} to={`/magazine/${issue.magazineId}`} size="sm">
                          <Badge color={COLORS[issue.status]} variant="dot" mr={6}>
                            {t(`status.issue.${issue.status}`)}
                          </Badge>
                          {issue.magazineTitle} · {issue.issueNumber}
                        </Anchor>
                      ))}
                    </Stack>
                  ))
              )}
            </Stack>
            <Group gap="xs">
              {(['wanted', 'downloaded', 'missing'] as const).map((status) => (
                <Badge key={status} color={COLORS[status]} variant={status === 'downloaded' ? 'filled' : 'light'}>
                  {t(`status.issue.${status}`)}
                </Badge>
              ))}
              <Text size="xs" c="dimmed">
                {t('calendar.help')}
              </Text>
            </Group>
          </>
        )}
      </QueryState>
    </Stack>
  );
}
