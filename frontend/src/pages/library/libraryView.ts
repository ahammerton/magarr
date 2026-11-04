import type { Frequency, Magazine } from '../../api/types';
import { t, type MessageKey } from '../../i18n';

/** A saved library filter: every set condition must hold. */
export interface LibraryFilter {
  id: string;
  name: string;
  monitored?: boolean;
  frequencies?: Frequency[];
  hasWanted?: boolean;
  complete?: boolean; // every issue downloaded
  hasFiles?: boolean;
  category?: string;
  tag?: string;
}

export type SortKey = 'title' | 'added' | 'size' | 'wanted' | 'custom';

const preset = (id: string, label: MessageKey, conditions: Partial<LibraryFilter> = {}) => ({
  id,
  name: label,
  ...conditions,
});

/** Built-in filters; their ``name`` is a message key. */
export const PRESETS: LibraryFilter[] = [
  preset('all', 'library.preset.all'),
  preset('monitored', 'library.preset.monitored', { monitored: true }),
  preset('unmonitored', 'library.preset.unmonitored', { monitored: false }),
  preset('wanted', 'library.preset.wanted', { hasWanted: true }),
  preset('complete', 'library.preset.complete', { complete: true }),
  preset('empty', 'library.preset.empty', { hasFiles: false }),
];

export function filterLabel(filter: LibraryFilter): string {
  return PRESETS.includes(filter) ? t(filter.name as MessageKey) : filter.name;
}

export function applies(filter: LibraryFilter, magazine: Magazine): boolean {
  const { issueCount, downloadedCount, wantedCount } = magazine.statistics;
  const is = (want: boolean | undefined, actual: boolean) => want === undefined || want === actual;
  const text = (want: string | undefined, values: (string | null)[]) =>
    !want?.trim() || values.some((v) => v?.toLowerCase().includes(want.trim().toLowerCase()));
  return (
    is(filter.monitored, magazine.monitored) &&
    is(filter.hasWanted, wantedCount > 0) &&
    is(filter.complete, issueCount > 0 && downloadedCount === issueCount) &&
    is(filter.hasFiles, downloadedCount > 0) &&
    (!filter.frequencies?.length || filter.frequencies.includes(magazine.frequency)) &&
    text(filter.category, [magazine.category]) &&
    text(filter.tag, magazine.tags)
  );
}

const COMPARE: Record<Exclude<SortKey, 'custom'>, (a: Magazine, b: Magazine) => number> = {
  title: (a, b) => a.sortTitle.localeCompare(b.sortTitle),
  added: (a, b) => b.added.localeCompare(a.added), // newest first
  size: (a, b) => b.statistics.sizeOnDisk - a.statistics.sizeOnDisk,
  wanted: (a, b) => b.statistics.wantedCount - a.statistics.wantedCount,
};

/** Sorted copy. The custom order lists magazine ids; ones not in it go last, by title. */
export function sortMagazines(magazines: Magazine[], key: SortKey, order: number[]): Magazine[] {
  if (key !== 'custom') return [...magazines].sort((a, b) => COMPARE[key](a, b) || COMPARE.title(a, b));
  const rank = new Map(order.map((id, index) => [id, index]));
  return [...magazines].sort(
    (a, b) => (rank.get(a.id) ?? Infinity) - (rank.get(b.id) ?? Infinity) || COMPARE.title(a, b),
  );
}

/** The custom order after dragging ``moved`` onto ``target`` (it takes the target's place). */
export function reorder(visible: number[], moved: number, target: number): number[] {
  const next = visible.filter((id) => id !== moved);
  const at = next.indexOf(target);
  next.splice(at === -1 ? next.length : visible.indexOf(moved) < visible.indexOf(target) ? at + 1 : at, 0, moved);
  return next;
}

// Per-browser conveniences: kept in localStorage, and fine to lose.
const KEYS = { filters: 'magarr.library.filters', sort: 'magarr.library.sort', order: 'magarr.library.order' };

function load<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function save(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage unavailable: the choice just won't persist.
  }
}

export const stored = {
  filters: () => load<LibraryFilter[]>(KEYS.filters, []),
  saveFilters: (filters: LibraryFilter[]) => save(KEYS.filters, filters),
  sort: () => load<SortKey>(KEYS.sort, 'title'),
  saveSort: (key: SortKey) => save(KEYS.sort, key),
  order: () => load<number[]>(KEYS.order, []),
  saveOrder: (order: number[]) => save(KEYS.order, order),
};
