import en from './en.json';

// All user-facing strings live in the locale files so the UI is localization-ready.
export type MessageKey = keyof typeof en;

const messages: Record<MessageKey, string> = en;

export function t(key: MessageKey, vars?: Record<string, string | number>): string {
  const template = messages[key];
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in vars ? String(vars[name]) : match,
  );
}
