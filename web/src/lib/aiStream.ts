import { create } from 'zustand';
import { getEditorEl, typeText } from './insert';
import { lsStore } from './lsStore';
import { toast } from '../store/toast';
import { renderPreviewNow } from './previewBus';
import { useSession } from '../store/session';

/* AI-помощник: порт runAI из editor.html. Протокол — NDJSON-стрим
   {t}/{error}/{done} из /api/ai (Ollama за сервером). Логика построчного
   буфера сохранена точно: чанк может рваться посреди строки. */

export const useAi = create<{ busy: boolean }>(() => ({ busy: false }));

interface AiMsg { t?: string; error?: string; ok?: boolean }

export async function runAI(
  action: 'rewrite' | 'format' | 'generate',
  text: string,
  selStart: number,
  selEnd: number,
): Promise<void> {
  const md = getEditorEl();
  if (!md) return;
  if (useAi.getState().busy) { toast('Модель ещё думает над прошлым запросом', true); return; }
  useAi.setState({ busy: true });
  toast('Модель пишет…');
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
      body: JSON.stringify({ action, text }),
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
    const msg = e instanceof Error ? e.message : String(e);
    toast(msg === 'Failed to fetch' ? 'Сервер недоступен' : msg, true);
  }
  md.readOnly = false;
  useAi.setState({ busy: false });
  lsStore.set('draft', md.value);
  renderPreviewNow();
}
