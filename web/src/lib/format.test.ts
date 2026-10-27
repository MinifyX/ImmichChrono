import { describe, expect, it } from 'vitest';
import { formatDate, formatShift, wallClock } from './format';

describe('format', () => {
  it('ignores offsets and keeps wall clock', () => {
    expect(wallClock('2019-03-01T12:30:00+01:00')?.getUTCHours()).toBe(12);
    expect(wallClock('nope')).toBeNull();
  });

  it('formats by precision', () => {
    expect(formatDate('2019-03-01T12:30:05', 'day')).toBe('1. März 2019');
    expect(formatDate('1987-06-01T12:00:00', 'decade')).toBe('1980er');
    expect(formatDate('2019-03-01T12:30:05')).toBe('1. März 2019, 12:30:05');
  });

  it('describes shifts', () => {
    expect(formatShift('2024-03-01T11:00:00', '2019-03-01T12:00:00')).toBe('−5 J.');
    expect(formatShift('2024-03-01T11:00:00', '2024-03-01T13:00:00')).toBe('+2 Std.');
  });
});
