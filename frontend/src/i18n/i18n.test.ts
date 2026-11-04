import { t } from '.';

describe('t', () => {
  it('returns the English string', () => {
    expect(t('nav.library')).toBe('Library');
  });
});
