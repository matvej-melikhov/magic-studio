import { lsStore } from './lsStore';

/* «Последние» эмодзи пикера: локальная история использования,
   новые в начале, без дублей, не больше RECENT_MAX.
   Кастомные — с emoji_id, стандартные юникодные — только alt (символ). */

export interface EmojiRef { emoji_id?: string; alt: string }

const KEY = 'recentEmojis';
export const RECENT_MAX = 20;

/* ключ уникальности: у кастомных id, у стандартных сам символ */
export const emojiKey = (e: EmojiRef): string => e.emoji_id || e.alt;

export function loadRecent(): EmojiRef[] {
  try {
    const list = JSON.parse(lsStore.get(KEY) || '[]') as EmojiRef[];
    return Array.isArray(list) ? list.filter((e) => e && (e.emoji_id || e.alt)) : [];
  } catch {
    return [];
  }
}

export function pushRecent(e: EmojiRef): EmojiRef[] {
  const current = loadRecent();
  // уже в списке — позицию не меняем, чтобы раскладка не «плыла»
  // от частых эмодзи; в начало встают только новые
  if (current.some((x) => emojiKey(x) === emojiKey(e))) return current;
  const list = [e, ...current].slice(0, RECENT_MAX);
  lsStore.set(KEY, JSON.stringify(list));
  return list;
}
