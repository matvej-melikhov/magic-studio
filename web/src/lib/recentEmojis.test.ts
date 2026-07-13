import { beforeEach, describe, expect, it, vi } from 'vitest';
import { RECENT_MAX, loadRecent, pushRecent } from './recentEmojis';

/* в vitest-среде глобальный localStorage — пустая заглушка node,
   поэтому подменяем его простым Map-хранилищем */
const store = new Map<string, string>();
vi.stubGlobal('localStorage', {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => void store.set(k, String(v)),
  removeItem: (k: string) => void store.delete(k),
  clear: () => store.clear(),
});

describe('recentEmojis', () => {
  beforeEach(() => store.clear());

  it('пусто по умолчанию и после мусора в хранилище', () => {
    expect(loadRecent()).toEqual([]);
    store.set('recentEmojis', 'не json');
    expect(loadRecent()).toEqual([]);
  });

  it('новые в начале, повтор не двигает позицию', () => {
    pushRecent({ emoji_id: '1', alt: '😺' });
    pushRecent({ emoji_id: '2', alt: '🔥' });
    expect(loadRecent().map((e) => e.emoji_id)).toEqual(['2', '1']);
    // повторное использование не меняет раскладку
    pushRecent({ emoji_id: '1', alt: '😺' });
    expect(loadRecent().map((e) => e.emoji_id)).toEqual(['2', '1']);
    // новый — в начало
    pushRecent({ emoji_id: '3', alt: '✨' });
    expect(loadRecent().map((e) => e.emoji_id)).toEqual(['3', '2', '1']);
  });

  it(`не больше ${RECENT_MAX}`, () => {
    for (let i = 0; i < RECENT_MAX + 5; i++) {
      pushRecent({ emoji_id: String(i), alt: 'x' });
    }
    const list = loadRecent();
    expect(list).toHaveLength(RECENT_MAX);
    expect(list[0].emoji_id).toBe(String(RECENT_MAX + 4)); // самый свежий
  });
});
