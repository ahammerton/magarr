import { Button, Group, Modal, Text } from '@mantine/core';

import { t } from '../i18n';

interface ConfirmModalProps {
  opened: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  loading?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

export function ConfirmModal(props: ConfirmModalProps) {
  return (
    <Modal opened={props.opened} onClose={props.onClose} title={props.title} centered>
      <Text size="sm">{props.message}</Text>
      <Group justify="flex-end" mt="lg">
        <Button variant="default" onClick={props.onClose}>
          {t('common.cancel')}
        </Button>
        <Button color="red" loading={props.loading} onClick={props.onConfirm}>
          {props.confirmLabel}
        </Button>
      </Group>
    </Modal>
  );
}
