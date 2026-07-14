import { useRef, useState } from 'react';
import Dropdown from './Dropdown';
import { api } from '../../api/client';
import { toast } from '../../store/toast';
import { insert, insertBlock, getEditorEl } from '../../lib/insert';
import { renderPreviewNow } from '../../lib/previewBus';
import { lsStore } from '../../lib/lsStore';
import {
  runAI, stopAI, markFragment, useAi,
  AI_TONE_PRESETS, getAiTone, setAiTonePreset, setAiToneCustom,
} from '../../lib/aiStream';

const sync = () => {
  const md = getEditorEl();
  if (md) lsStore.set('draft', md.value);
  renderPreviewNow();
};

/* ── Кастомные эмодзи: пикер из сохранённых через бота ── */
interface EmojiGroup { id: string; name: string; emojis: Array<{ emoji_id: string; alt: string }> }

export function EmojiButton() {
  const btnRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [groups, setGroups] = useState<EmojiGroup[]>([]);

  const toggle = async () => {
    if (open) { setOpen(false); return; }
    const resp = await api('/api/emojis');
    setGroups((resp.ok && (resp.groups as EmojiGroup[])) || []);
    setOpen(true);
  };

  const pick = (e: { emoji_id: string; alt: string }) => {
    setOpen(false);
    insert(`![${e.alt}](tg://emoji?id=${e.emoji_id})`, '', '');
    sync();
  };

  return (
    <span className="media-wrap">
      <button ref={btnRef} id="emojiBtn"
        title="Кастомные эмодзи — пришлите их боту, чтобы пополнить"
        onClick={() => void toggle()}>
        <svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><circle cx="8" cy="8" r="6.3"/><path d="M5.4 9.4c.6 1 1.5 1.6 2.6 1.6s2-.6 2.6-1.6"/><circle cx="5.9" cy="6.3" r=".65" fill="currentColor" stroke="none"/><circle cx="10.1" cy="6.3" r=".65" fill="currentColor" stroke="none"/></svg>
      </button>
      <Dropdown anchorRef={btnRef} open={open} onClose={() => setOpen(false)} className="emoji-menu">
        {groups.length ? (
          groups.map((g, gi) => (
            <span key={g.id} style={{ display: 'contents' }}>
              {g.name
                ? <div className="egroup">{g.name}</div>
                : groups.length > 1 && <div className="egroup">Без группы</div>}
              {g.emojis.map((e) => (
                <button key={e.emoji_id + gi} className="em" title={e.alt} onClick={() => pick(e)}>
                  <img src={`api/emoji/img?id=${e.emoji_id}`} alt={e.alt} loading="lazy"
                    onError={(ev) => ev.currentTarget.closest('button')?.remove()} />
                </button>
              ))}
            </span>
          ))
        ) : (
          <div className="emoji-hint">
            Коллекций пока нет. В боте: /emoji → «Добавить паки» → пришлите
            сообщение с кастомными эмодзи — их паки добавятся целиком.
          </div>
        )}
      </Dropdown>
    </span>
  );
}

/* ── Медиа: одна кнопка с меню «файл / по ссылке» ── */
export function MediaButton() {
  const btnRef = useRef<HTMLButtonElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);

  const uploadFile = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    if (file.size > 45 * 1024 * 1024) {
      toast('Файл больше 45 МБ — Telegram не примет такое медиа по ссылке', true);
      fileRef.current!.value = '';
      return;
    }
    toast('Загрузка медиа…');
    const data = await new Promise<string>((res) => {
      const r = new FileReader();
      r.onload = () => res((r.result as string).split(',')[1]);
      r.readAsDataURL(file);
    });
    const resp = await api('/api/upload', { name: file.name, data });
    if (resp.ok) {
      insertBlock('![](' + resp.url + ' "Подпись")', '');
      toast('Медиа добавлено');
      sync();
    } else toast(resp.error || 'Ошибка', true);
    fileRef.current!.value = '';
  };

  const byUrl = () => {
    setOpen(false);
    const url = prompt('Ссылка на картинку (https://…):');
    if (!url) return;
    if (!/^https?:\/\//i.test(url.trim())) { toast('Нужна http(s)-ссылка', true); return; }
    insertBlock('![](' + url.trim() + ' "Подпись")', '');
    sync();
  };

  return (
    <span className="media-wrap">
      <button ref={btnRef} id="mediaBtn" title="Медиа: фото, видео, аудио, гиф"
        onClick={() => setOpen((o) => !o)}>
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
      </button>
      <Dropdown anchorRef={btnRef} open={open} onClose={() => setOpen(false)}>
        <button onClick={() => { setOpen(false); fileRef.current?.click(); }}>Выбрать файл</button>
        <button onClick={byUrl}>По ссылке</button>
      </Dropdown>
      <input type="file" ref={fileRef} accept="image/*,video/*,audio/*" hidden
        onChange={() => void uploadFile()} />
    </span>
  );
}

/* ── AI-помощник: локальная модель через сервер (/api/ai → Ollama) ──
   Меню двухшаговое: сначала выбор действия, а для «переписать»/«с нуля» —
   второй экран с выбором тона (у «оформить» тона нет, слова не меняются).
   generate спрашивает тему ПОСЛЕ тона: prompt() — блокирующий системный
   диалог, поэтому дропдаун закрываем ДО его вызова (как везде в этом
   файле — anchor()/map()/byUrl() — иначе конфликтует с обработчиком
   клика вне меню и генерация срывается молча). */
interface PendingRewrite { action: 'rewrite'; text: string; s: number; e: number; context?: string }
interface PendingGenerate { action: 'generate' }
type PendingRun = PendingRewrite | PendingGenerate;

export function AiButton() {
  const btnRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<PendingRun | null>(null);
  const busy = useAi((s) => s.busy);
  const [tone, setTone] = useState(getAiTone());

  const close = () => { setOpen(false); setPending(null); };

  const execute = (run: PendingRun, toneKey: string) => {
    close();
    if (run.action === 'generate') {
      const q = prompt('О чём написать пост?');
      if (!q || !q.trim()) return;
      const md = getEditorEl();
      if (!md) return;
      /* «с нуля» — новый пост вместо текущего: выделяем всё, сгенерированный
         текст заменит содержимое (вставка идёт через execCommand, Ctrl+Z вернёт) */
      void runAI('generate', q.trim(), 0, md.value.length, undefined, toneKey || undefined);
    } else {
      void runAI('rewrite', run.text, run.s, run.e, run.context, toneKey || undefined);
    }
  };

  const pickTonePreset = (key: string) => {
    setAiTonePreset(key);
    setTone(getAiTone());
    if (pending) execute(pending, key);
  };

  const pickCustomTone = () => {
    if (!pending) return;
    const run = pending;
    close();
    const text = prompt(
      'Опишите тон и стиль своими словами (например «саркастично, с юмором»):',
      tone.preset === 'custom' ? tone.custom : '',
    );
    if (text === null) return;
    const toneText = text.trim();
    if (toneText) { setAiToneCustom(toneText); setTone(getAiTone()); }
    execute(run, toneText);
  };

  const withSel = (fn: (md: HTMLTextAreaElement, s: number, e: number) => void) => {
    const md = getEditorEl();
    if (md) fn(md, md.selectionStart, md.selectionEnd);
  };

  const rewrite = () => withSel((md, s, e) => {
    if (s === e) { toast('Выделите текст, который нужно переписать', true); setOpen(false); return; }
    /* фрагмент внутри целого поста — модель стыкует стиль с окружением */
    const context = e - s < md.value.length ? markFragment(md.value, s, e) : undefined;
    setPending({ action: 'rewrite', text: md.value.slice(s, e), s, e, context });
  });

  const format = () => withSel((md, s, e) => {
    const hasSel = s !== e;
    const text = hasSel ? md.value.slice(s, e) : md.value;
    if (!text.trim()) { toast('Пост пустой — оформлять нечего', true); close(); return; }
    const context = hasSel && text.length < md.value.length
      ? markFragment(md.value, s, e) : undefined;
    void runAI('format', text, hasSel ? s : 0, hasSel ? e : md.value.length, context);
    close();
  });

  const generate = () => setPending({ action: 'generate' });

  return (
    <span className="group ai-group">
      <span className="media-wrap">
        {/* во время генерации кнопка превращается в «Стоп» */}
        <button ref={btnRef} id="aiBtn"
          title={busy ? 'Остановить генерацию' : 'AI-помощник'}
          className={busy ? 'ai-busy' : ''}
          onClick={() => { if (busy) stopAI(); else { setPending(null); setOpen((o) => !o); } }}>
          {busy
            ? <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
            : <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9z"/></svg>}
        </button>
        <Dropdown anchorRef={btnRef} open={open} onClose={close}>
          {pending ? (
            <>
              <button className="ai-menu-back" onClick={() => setPending(null)}>← Назад</button>
              <div className="ai-tone-label">Тон</div>
              {AI_TONE_PRESETS.map((p) => (
                <button key={p.key || 'neutral'}
                  className={tone.preset === p.key ? 'ai-tone-active' : ''}
                  onClick={() => pickTonePreset(p.key)}>
                  {tone.preset === p.key ? '✓ ' : ''}{p.label}
                </button>
              ))}
              <button className={tone.preset === 'custom' ? 'ai-tone-active' : ''}
                onClick={pickCustomTone}>
                {tone.preset === 'custom' && tone.custom
                  ? `✓ Свой: ${tone.custom}` : 'Свой…'}
              </button>
            </>
          ) : (
            <>
              <button onClick={rewrite}>Переписать выделенное</button>
              <button onClick={format}>Оформить разметкой</button>
              <button onClick={generate}>Написать с нуля…</button>
            </>
          )}
        </Dropdown>
      </span>
    </span>
  );
}
