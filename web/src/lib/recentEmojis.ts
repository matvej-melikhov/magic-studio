import { lsStore } from './lsStore';

/* «Последние» эмодзи пикера: локальная история использования,
   свежие в начале, без дублей, не больше RECENT_MAX. */

export interface EmojiRef { emoji_id: string; alt: string }

const KEY = 'recentEmojis';
export const RECENT_MAX = 20;

export function loadRecent(): EmojiRef[] {
  try {
    const list = JSON.parse(lsStore.get(KEY) || '[]') as EmojiRef[];
    return Array.isArray(list) ? list.filter((e) => e && e.emoji_id) : [];
  } catch {
    return [];
  }
}

export function pushRecent(e: EmojiRef): EmojiRef[] {
  const current = loadRecent();
  // уже в списке — позицию не меняем, чтобы раскладка не «плыла»
  // от частых эмодзи; в начало встают только новые
  if (current.some((x) => x.emoji_id === e.emoji_id)) return current;
  const list = [e, ...current].slice(0, RECENT_MAX);
  lsStore.set(KEY, JSON.stringify(list));
  return list;
}
