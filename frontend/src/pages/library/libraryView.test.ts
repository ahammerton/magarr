import { makeMagazine } from '../../test/handlers';
import { applies, PRESETS, reorder, sortMagazines } from './libraryView';

const stats = (issueCount: number, downloadedCount: number, wantedCount: number, sizeOnDisk = 0) => ({
  issueCount,
  downloadedCount,
  wantedCount,
  sizeOnDisk,
});
const ng = makeMagazine({ id: 1, title: 'National Geographic', sortTitle: 'national geographic', statistics: stats(3, 3, 0, 500), added: '2026-01-01T00:00:00Z' });
const wired = makeMagazine({ id: 2, title: 'Wired', sortTitle: 'wired', monitored: false, frequency: 'weekly', tags: ['tech'], category: 'Technology', statistics: stats(4, 1, 2, 900), added: '2026-05-01T00:00:00Z' });
const viz = makeMagazine({ id: 3, title: 'Viz', sortTitle: 'viz', statistics: stats(2, 0, 2, 0), added: '2026-03-01T00:00:00Z' });
const all = [ng, wired, viz];
const preset = (id: string) => PRESETS.find((p) => p.id === id)!;

describe('library filters', () => {
  it.each([
    ['all', [1, 2, 3]],
    ['monitored', [1, 3]],
    ['unmonitored', [2]],
    ['wanted', [2, 3]],
    ['complete', [1]],
    ['empty', [3]],
  ])('%s', (id, expected) => {
    expect(all.filter((m) => applies(preset(id), m)).map((m) => m.id)).toEqual(expected);
  });

  it('combines conditions in custom filters', () => {
    const custom = { id: 'x', name: 'Weekly tech', frequencies: ['weekly' as const], tag: 'TECH', category: 'tech' };
    expect(all.filter((m) => applies(custom, m)).map((m) => m.id)).toEqual([2]);
    expect(applies({ ...custom, monitored: true }, wired)).toBe(false);
  });
});

describe('library sorting', () => {
  it('sorts by title, newest, size or wanted', () => {
    expect(sortMagazines(all, 'title', []).map((m) => m.id)).toEqual([1, 3, 2]);
    expect(sortMagazines(all, 'added', []).map((m) => m.id)).toEqual([2, 3, 1]);
    expect(sortMagazines(all, 'size', []).map((m) => m.id)).toEqual([2, 1, 3]);
    expect(sortMagazines(all, 'wanted', []).map((m) => m.id)).toEqual([3, 2, 1]); // ties by title
  });

  it('keeps a custom order, with new magazines last', () => {
    expect(sortMagazines(all, 'custom', [3, 1]).map((m) => m.id)).toEqual([3, 1, 2]);
  });

  it('reorders by dropping one poster on another', () => {
    expect(reorder([1, 2, 3, 4], 1, 3)).toEqual([2, 3, 1, 4]); // moved forward: after the target
    expect(reorder([1, 2, 3, 4], 4, 2)).toEqual([1, 4, 2, 3]); // moved back: before the target
  });
});
