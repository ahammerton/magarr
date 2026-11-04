import { Alert, List, NumberInput, PasswordInput, Select, Switch, TextInput, Textarea } from '@mantine/core';
import { IconAlertTriangle, IconCheck } from '@tabler/icons-react';

import type { ClientTestResult, FieldSchema } from '../api/types';
import { t } from '../i18n';

/** Result of a "Test" button: connected (with any warnings) or the error. */
export function TestOutcome({ result }: { result: ClientTestResult | undefined }) {
  if (!result) return null;
  const color = !result.ok ? 'red' : result.warnings.length ? 'orange' : 'teal';
  return (
    <Alert
      color={color}
      icon={result.ok ? <IconCheck /> : <IconAlertTriangle />}
      title={result.ok ? result.message : t('indexers.test.failed')}
    >
      {!result.ok && result.message}
      {result.warnings.length > 0 && (
        <List size="sm">
          {result.warnings.map((w) => (
            <List.Item key={w}>{w}</List.Item>
          ))}
        </List>
      )}
    </Alert>
  );
}

/** One input per schema field, so new client or notification types need no UI changes. */
export function SettingField({
  field,
  value,
  onChange,
}: {
  field: FieldSchema;
  value: string | number | boolean | undefined;
  onChange: (value: string | number | boolean) => void;
}) {
  const common = { label: field.label, description: field.description ?? undefined, withAsterisk: field.required };
  switch (field.type) {
    case 'boolean':
      return (
        <Switch
          label={field.label}
          description={field.description ?? undefined}
          checked={Boolean(value)}
          onChange={(e) => onChange(e.currentTarget.checked)}
        />
      );
    case 'number':
      return <NumberInput {...common} value={value as number} allowDecimal={false} onChange={(v) => onChange(v === '' ? '' : Number(v))} />;
    case 'password':
      return <PasswordInput {...common} value={String(value ?? '')} onChange={(e) => onChange(e.currentTarget.value)} />;
    case 'select':
      return (
        <Select
          {...common}
          data={field.options ?? []}
          value={String(value ?? '')}
          allowDeselect={false}
          onChange={(v) => v !== null && onChange(v)}
        />
      );
    case 'textarea':
      return <Textarea {...common} autosize minRows={2} value={String(value ?? '')} onChange={(e) => onChange(e.currentTarget.value)} />;
    default:
      return <TextInput {...common} value={String(value ?? '')} onChange={(e) => onChange(e.currentTarget.value)} />;
  }
}

