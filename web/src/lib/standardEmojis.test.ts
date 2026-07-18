import { describe, expect, it } from 'vitest';
import { VERSION_PROBES, standardEmojis } from './standardEmojis';

describe('standardEmojis', () => {
  it('без лимита отдаёт полный набор в 9 категориях', () => {
    const all = standardEmojis(Infinity);
    expect(all).toHaveLength(9);
    expect(all.reduce((n, g) => n + g.chars.length, 0)).toBe(1914);
  });

  it('фильтр по версии отсекает свежие эмодзи', () => {
    const count = (v: number) =>
      standardEmojis(v).reduce((n, g) => n + g.chars.length, 0);
    expect(count(15.0)).toBeLessThan(count(Infinity));
    expect(count(12.0)).toBeLessThan(count(15.0));
    // смайлы первой версии есть всегда
    expect(standardEmojis(0.6)[0].chars).toContain('😃');
  });

  it('пробы версий идут от новых к старым', () => {
    const versions = VERSION_PROBES.map(([v]) => v);
    expect(versions).toEqual([...versions].sort((a, b) => b - a));
  });
});
