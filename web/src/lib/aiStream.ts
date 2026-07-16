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

/* lastRun — параметры последнего успешного запроса + диапазон, куда лёг
   ответ: пока он не null, тулбар показывает кнопку «Ещё вариант» рядом
   с AI-кнопкой (см. AiButton в ToolbarExtras.tsx). Сбрасывается в начале
   каждого нового runAI и по любому другому действию пользователя. */
export interface RegenerateInfo {
  action: 'rewrite' | 'format' | 'generate';
  text: string; selStart: number; selEnd: number;
  context?: string; tone?: string; refs?: string[]; words?: number;
}
export const useAi = create<{ busy: boolean; lastRun: RegenerateInfo | null }>(
  () => ({ busy: false, lastRun: null }),
);

export function regenerateLast(): void {
  const r = useAi.getState().lastRun;
  if (r) void runAI(r.action, r.text, r.selStart, r.selEnd, r.context, r.tone, r.refs, r.words);
}

/* Пресеты объёма для generate; words undefined = «как обычно в канале»
   (сервер возьмёт медиану опубликованных постов). Явный размер в тексте
   запроса («в два предложения») главнее любого пресета. */
export const AI_LEN_PRESETS: Array<{ key: string; label: string; words?: number }> = [
  { key: '', label: 'Авто — как в канале' },
  { key: 'short', label: 'Короткий (~50 слов)', words: 50 },
  { key: 'medium', label: 'Средний (~150 слов)', words: 150 },
  { key: 'long', label: 'Длинный (~400 слов)', words: 400 },
];

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
  words?: number,
): Promise<void> {
  const md = getEditorEl();
  if (!md) return;
  if (useAi.getState().busy) { toast('Модель ещё думает над прошлым запросом', true); return; }
  useAi.setState({ busy: true, lastRun: null });
  aborter = new AbortController();
  toast('Модель пишет… (повторный клик по кнопке AI — остановить)');
  /* пока идёт стрим, редактор только для чтения — иначе ручной ввод
     собьёт позицию вставки; на момент вставки чанка флаг снимается,
     т.к. execCommand не работает в readonly-поле.
     spellcheck на время стрима гасим: execCommand — это «печать» для
     браузера, и умные замены Safari превращали --- модели в длинное
     тире прямо в textarea (артефакт-«разделитель»); заодно off и
     autocapitalize, чтобы iOS не поднимал регистр после точек */
  md.readOnly = true;
  const prevSpell = md.spellcheck;
  const prevCap = md.autocapitalize;
  md.spellcheck = false;
  md.autocapitalize = 'off';
  /* expected — точный текст от сервера; pos — по фактической каретке,
     а не арифметикой: умные замены браузера меняют длину вставленного */
  let pos = selStart, first = true, expected = '';
  const put = (t: string) => {
    md.readOnly = false;
    if (first) { typeText(t, selStart, selEnd); first = false; }
    else typeText(t, pos, pos);
    pos = md.selectionStart;
    expected += t;
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
      body: JSON.stringify({ action, text, context, tone, refs, words }),
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
    /* Сверка: браузер мог «поумничать» при вставке (умные тире Safari
       превращали --- в —). Фактически вставленное сравнивается с текстом
       от сервера; разошлось — перевставляем правильный одной заменой
       (плюс один шаг в истории отмены). Если браузер испортил и повторную
       вставку — setRangeText кладёт текст в обход пайплайна печати. */
    const actual = md.value.slice(selStart, pos);
    if (actual !== expected) {
      md.readOnly = false;
      typeText(expected, selStart, pos);
      pos = md.selectionStart;
      if (md.value.slice(selStart, pos) !== expected) {
        md.setRangeText(expected, selStart, pos, 'end');
        pos = selStart + expected.length;
      }
      md.readOnly = true;
    }
    /* «Ещё вариант» — тот же запрос ещё раз, заменяя именно диапазон,
       куда лёг этот ответ (selStart…pos), а не текст целиком */
    useAi.setState({
      lastRun: { action, text, selStart, selEnd: pos, context, tone, refs, words },
    });
    toast('Готово. Не понравилось — есть кнопка «Ещё вариант» или Ctrl+Z');
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
  md.spellcheck = prevSpell;
  md.autocapitalize = prevCap;
  useAi.setState({ busy: false });
  lsStore.set('draft', md.value);
  renderPreviewNow();
}
