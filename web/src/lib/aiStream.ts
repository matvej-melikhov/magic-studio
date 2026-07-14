import { create } from 'zustand';
import { getEditorEl, typeText } from './insert';
import { lsStore } from './lsStore';
import { toast } from '../store/toast';
import { renderPreviewNow } from './previewBus';
import { useSession } from '../store/session';

/* AI-помощник. Протокол — NDJSON-стрим {t}/{error}/{done} из /api/ai
   (Ollama за сервером). Логика построчного буфера сохранена точно:
   чанк может рваться посреди строки.

   Для правок выделенного на сервер уходит и context: пост целиком
   с фрагментом, помеченным <<< >>>, — модель видит окружение и
   стыкует стиль (правка «вслепую» давала стилистические разрывы). */

export const useAi = create<{ busy: boolean }>(() => ({ busy: false }));

interface AiMsg { t?: string; error?: string; ok?: boolean }

/* Тон для rewrite/generate (format слова не меняет — тон там неприменим).
   Пресеты — ключи должны совпадать с AI_TONES в app/core.py. Выбор хранится
   в localStorage, чтобы не выбирать заново при каждом запросе. */
export const AI_TONE_PRESETS: Array<{ key: string; label: string }> = [
  { key: '', label: 'Нейтральный' },
  { key: 'business', label: 'Деловой' },
  { key: 'casual', label: 'Неформальный' },
  { key: 'friendly', label: 'Дружелюбный' },
  { key: 'expert', label: 'Экспертный' },
];

export function getAiTone(): { preset: string; custom: string } {
  return {
    preset: lsStore.get('aiTonePreset') || '',
    custom: lsStore.get('aiToneCustom') || '',
  };
}

export function setAiTonePreset(key: string): void {
  lsStore.set('aiTonePreset', key);
}

export function setAiToneCustom(text: string): void {
  lsStore.set('aiToneCustom', text);
  lsStore.set('aiTonePreset', 'custom');
}

/* Маркеры фрагмента — те же, что в core.py (FRAG_OPEN/FRAG_CLOSE) */
export function markFragment(full: string, selStart: number, selEnd: number): string {
  return full.slice(0, selStart) + '<<<' + full.slice(selStart, selEnd) +
    '>>>' + full.slice(selEnd);
}

let aborter: AbortController | null = null;

/* Остановка генерации: сервер прервёт свой генератор, вставленный
   к этому моменту текст остаётся (Ctrl+Z вернёт как было) */
export function stopAI(): void {
  aborter?.abort();
}

export async function runAI(
  action: 'rewrite' | 'format' | 'generate',
  text: string,
  selStart: number,
  selEnd: number,
  context?: string,
  tone?: string,
  refs?: string[],
): Promise<void> {
  const md = getEditorEl();
  if (!md) return;
  if (useAi.getState().busy) { toast('Модель ещё думает над прошлым запросом', true); return; }
  useAi.setState({ busy: true });
  aborter = new AbortController();
  toast('Модель пишет… (повторный клик по кнопке AI — остановить)');
  /* пока идёт стрим, редактор только для чтения — иначе ручной ввод
     собьёт позицию вставки; на момент вставки чанка флаг снимается,
     т.к. execCommand не работает в readonly-поле */
  md.readOnly = true;
  let pos = selStart, first = true;
  const put = (t: string) => {
    md.readOnly = false;
    if (first) { typeText(t, selStart, selEnd); first = false; pos = selStart + t.length; }
    else { typeText(t, pos, pos); pos += t.length; }
    md.readOnly = true;
  };
  try {
    const r = await fetch('api/ai', {
      method: 'POST',
      headers: {
        'X-Session': lsStore.get('session') || '',
        'Content-Type': 'application/json',
      },
      /* refs — id прошлых постов канала как образец стиля; сервер сам достаёт
         их markdown из БД. Пустой список = «без примеров» (не то же самое,
         что отсутствие поля — тогда сервер возьмёт последние посты сам). */
      body: JSON.stringify({ action, text, context, tone, refs }),
      signal: aborter.signal,
    });
    if (r.status === 401) {
      useSession.getState().showLogin();
      throw new Error('Нужен вход');
    }
    const reader = r.body!.getReader();
    const dec = new TextDecoder();
    let buf = '';
    const handle = (msg: AiMsg) => {
      if (msg.error || msg.ok === false) throw new Error(msg.error || 'Ошибка');
      if (msg.t) put(msg.t);
    };
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf('\n')) !== -1) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (line) handle(JSON.parse(line));
      }
    }
    if (buf.trim()) handle(JSON.parse(buf)); // не-стримовый ответ (ранняя ошибка)
    if (first) throw new Error('Модель вернула пустой ответ.');
    toast('Готово. Не понравилось — Ctrl+Z вернёт как было');
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') {
      toast('Остановлено. Ctrl+Z уберёт вставленное');
    } else {
      const msg = e instanceof Error ? e.message : String(e);
      toast(msg === 'Failed to fetch' ? 'Сервер недоступен' : msg, true);
    }
  }
  aborter = null;
  md.readOnly = false;
  useAi.setState({ busy: false });
  lsStore.set('draft', md.value);
  renderPreviewNow();
}
