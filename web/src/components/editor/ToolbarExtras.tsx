import { useRef, useState } from 'react';
import Dropdown from './Dropdown';
import { api } from '../../api/client';
import { toast } from '../../store/toast';
import { insert, insertBlock, getEditorEl } from '../../lib/insert';
import { renderPreviewNow } from '../../lib/previewBus';
import { lsStore } from '../../lib/lsStore';
import { fmtDate } from '../../lib/format';
import { useAppState } from '../../store/appState';
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
   Меню трёхшаговое: действие → тон → посты-референсы (образец авторского
   стиля). «Оформить разметкой» идёт сразу: там слова не меняются, поэтому
   ни тон, ни стиль неприменимы. Тема поста для «с нуля» спрашивается
   сразу при выборе действия — дальше идут только экраны меню, чтобы
   блокирующий prompt() не всплывал после финальной кнопки. */
interface PendingRewrite { action: 'rewrite'; text: string; s: number; e: number; context?: string }
interface PendingGenerate { action: 'generate'; text: string }
type PendingRun = PendingRewrite | PendingGenerate;

const REFS_MAX = 3;   // столько же берёт сервер (core.AI_REFS_MAX)

export function AiButton() {
  const btnRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<PendingRun | null>(null);
  const [step, setStep] = useState<'tone' | 'refs'>('tone');
  const [toneKey, setToneKey] = useState('');
  const [refs, setRefs] = useState<string[]>([]);
  const busy = useAi((s) => s.busy);
  const [tone, setTone] = useState(getAiTone());
  const published = useAppState((s) => s.published);

  const close = () => { setOpen(false); setPending(null); setStep('tone'); };

  /* по умолчанию — последние посты канала; их же сервер взял бы сам */
  const toRefs = (key: string) => {
    setToneKey(key);
    setRefs(published.slice(0, REFS_MAX).map((p) => p.id));
    setStep('refs');
  };

  const pickTonePreset = (key: string) => {
    setAiTonePreset(key);
    setTone(getAiTone());
    toRefs(key);
  };

  const pickCustomTone = () => {
    const text = prompt(
      'Опишите тон и стиль своими словами (например «саркастично, с юмором»):',
      tone.preset === 'custom' ? tone.custom : '',
    );
    if (text === null) return;
    const toneText = text.trim();
    if (toneText) { setAiToneCustom(toneText); setTone(getAiTone()); }
    toRefs(toneText);
  };

  const toggleRef = (id: string) => setRefs((cur) => (
    cur.includes(id) ? cur.filter((x) => x !== id)
      : cur.length >= REFS_MAX ? cur
        : [...cur, id]
  ));

  const execute = () => {
    if (!pending) return;
    const run = pending;
    close();
    if (run.action === 'generate') {
      const md = getEditorEl();
      if (!md) return;
      /* «с нуля» — новый пост вместо текущего: выделяем всё, сгенерированный
         текст заменит содержимое (вставка идёт через execCommand, Ctrl+Z вернёт) */
      void runAI('generate', run.text, 0, md.value.length, undefined,
        toneKey || undefined, refs);
    } else {
      void runAI('rewrite', run.text, run.s, run.e, run.context,
        toneKey || undefined, refs);
    }
  };

  const withSel = (fn: (md: HTMLTextAreaElement, s: number, e: number) => void) => {
    const md = getEditorEl();
    if (md) fn(md, md.selectionStart, md.selectionEnd);
  };

  const rewrite = () => withSel((md, s, e) => {
    if (s === e) { toast('Выделите текст, который нужно переписать', true); setOpen(false); return; }
    /* фрагмент внутри целого поста — модель стыкует стиль с окружением */
    const context = e - s < md.value.length ? markFragment(md.value, s, e) : undefined;
    setStep('tone');
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

  const generate = () => {
    const q = prompt('О чём написать пост?');
    if (!q || !q.trim()) { setOpen(false); return; }
    setStep('tone');
    setPending({ action: 'generate', text: q.trim() });
  };

  return (
    <span className="group ai-group">
      <span className="media-wrap">
        {/* во время генерации кнопка превращается в «Стоп» */}
        <button ref={btnRef} id="aiBtn"
          title={busy ? 'Остановить генерацию' : 'AI-помощник'}
          className={busy ? 'ai-busy' : ''}
          onClick={() => { if (busy) stopAI(); else { setPending(null); setStep('tone'); setOpen((o) => !o); } }}>
          {busy
            ? <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
            : <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9z"/></svg>}
        </button>
        <Dropdown anchorRef={btnRef} open={open} onClose={close}>
          {!pending ? (
            <>
              <button onClick={rewrite}>Переписать выделенное</button>
              <button onClick={format}>Оформить разметкой</button>
              <button onClick={generate}>Написать с нуля…</button>
            </>
          ) : step === 'tone' ? (
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
            <span className="ai-refs">
              <button className="ai-menu-back" onClick={() => setStep('tone')}>← Назад</button>
              <div className="ai-tone-label">Писать в стиле этих постов</div>
              {published.length ? (
                published.slice(0, 12).map((p) => (
                  <button key={p.id} className="ai-ref"
                    onClick={() => toggleRef(p.id)}
                    disabled={!refs.includes(p.id) && refs.length >= REFS_MAX}>
                    <span className="ai-ref-box">{refs.includes(p.id) ? '☑' : '☐'}</span>
                    <span className="ai-ref-title">{p.title || 'Без заголовка'}</span>
                    <span className="ai-ref-date">{fmtDate(p.when)}</span>
                  </button>
                ))
              ) : (
                <div className="emoji-hint">
                  Опубликованных постов пока нет — примеров стиля не будет.
                  Они появятся здесь после первой публикации через студию.
                </div>
              )}
              <hr className="ai-menu-sep" />
              <button className="ai-run" onClick={execute}>
                {refs.length
                  ? `Написать (примеров: ${refs.length})`
                  : 'Написать без примеров'}
              </button>
            </span>
          )}
        </Dropdown>
      </span>
    </span>
  );
}
