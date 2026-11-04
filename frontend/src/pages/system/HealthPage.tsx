import { Alert, Button, Card, Group, Stack, Text, ThemeIcon } from '@mantine/core';
import { IconAlertTriangle, IconCircleCheck, IconInfoCircle, IconRefresh, IconX } from '@tabler/icons-react';

import { useCheckHealth, useHealth } from '../../api/systemPages';
import type { HealthLevel } from '../../api/types';
import { PageHeader } from '../../components/PageHeader';
import { QueryState } from '../../components/QueryState';
import { formatRelative } from '../../format';
import { t } from '../../i18n';
import { notifyError } from '../../notify';

const LEVELS: Record<HealthLevel, { color: string; icon: typeof IconX }> = {
  error: { color: 'red', icon: IconX },
  warning: { color: 'orange', icon: IconAlertTriangle },
  notice: { color: 'blue', icon: IconInfoCircle },
};

export function HealthPage() {
  const health = useHealth();
  const check = useCheckHealth();
  return (
    <Stack gap="lg" maw={900}>
      <PageHeader title={t('nav.system.health')}>
        <Button
          variant="default"
          leftSection={<IconRefresh size={16} />}
          loading={check.isPending}
          onClick={() => check.mutate(undefined, { onError: notifyError })}
        >
          {t('health.checkNow')}
        </Button>
      </PageHeader>
      <QueryState isPending={health.isPending} error={health.error}>
        {() => (
          <Stack>
            {health.data!.items.length === 0 ? (
              <Alert color="teal" icon={<IconCircleCheck />} title={t('health.ok.title')}>
                {t('health.ok.body')}
              </Alert>
            ) : (
              <Card withBorder padding="sm">
                <Stack gap="xs">
                  {health.data!.items.map((item) => {
                    const { color, icon: Icon } = LEVELS[item.level];
                    return (
                      <Group key={item.message} gap="sm" wrap="nowrap" data-testid="health-item">
                        <ThemeIcon color={color} variant="light" aria-label={t(`health.level.${item.level}`)}>
                          <Icon size={16} />
                        </ThemeIcon>
                        <Text size="sm">{item.message}</Text>
                      </Group>
                    );
                  })}
                </Stack>
              </Card>
            )}
            <Text size="xs" c="dimmed">
              {t('health.checked', { when: formatRelative(health.data!.checkedAt) })}
            </Text>
          </Stack>
        )}
      </QueryState>
    </Stack>
  );
}
