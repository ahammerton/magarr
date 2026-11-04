import { formatUptime } from './format';

describe('formatUptime', () => {
  it.each([
    [0, '00:00:00'],
    [59, '00:00:59'],
    [3725, '01:02:05'],
    [90061, '1d 01:01:01'],
  ])('%i seconds → %s', (seconds, expected) => {
    expect(formatUptime(seconds)).toBe(expected);
  });
});
