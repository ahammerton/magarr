import { Group, Title } from '@mantine/core';
import type { ReactNode } from 'react';

export function PageHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <Group justify="space-between" align="center" wrap="wrap" gap="sm">
      <Title order={2}>{title}</Title>
      {children && <Group gap="xs">{children}</Group>}
    </Group>
  );
}
