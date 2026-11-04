import { Center, Stack, Text, ThemeIcon, Title } from '@mantine/core';
import { IconInbox } from '@tabler/icons-react';

import { t, type MessageKey } from '../i18n';

interface EmptyPageProps {
  title: MessageKey;
  description: MessageKey;
}

export function EmptyPage({ title, description }: EmptyPageProps) {
  return (
    <Stack gap="lg">
      <Title order={2}>{t(title)}</Title>
      <Center py={80}>
        <Stack align="center" gap="xs">
          <ThemeIcon variant="light" size={56} radius="xl">
            <IconInbox size={30} stroke={1.5} />
          </ThemeIcon>
          <Text fw={600}>{t('empty.title')}</Text>
          <Text c="dimmed" size="sm">
            {t(description)}
          </Text>
        </Stack>
      </Center>
    </Stack>
  );
}
