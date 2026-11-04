import type { ClientSettingsValues, FieldSchema } from '../api/types';

/** Initial values for a schema-driven settings form. */
export function defaults(fields: FieldSchema[]): ClientSettingsValues {
  return Object.fromEntries(
    fields.map((f) => [f.name, f.default ?? (f.type === 'boolean' ? false : '')]),
  ) as ClientSettingsValues;
}
