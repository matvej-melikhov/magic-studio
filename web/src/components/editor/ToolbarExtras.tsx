import { useRef, useState } from 'react';
import Dropdown from './Dropdown';
import { api } from '../../api/client';
import { toast } from '../../store/toast';
import { insert, insertBlock, getEditorEl } from '../../lib/insert';
import { renderPreviewNow } from '../../lib/previewBus';
import { lsStore } from '../../lib/lsStore';
import { emojiKey, pruneRecent, pushRecent, type EmojiRef } from '../../lib/recentEmojis';
import { standardEmojis } from '../../lib/standardEmojis';
import { maxEmojiVersion } from '../../lib/emojiSupport';
import { runAI, useAi } from '../../lib/aiStream';

const sync = () => {
  const md = getEditorEl();
  if (md) lsStore.set('draft', md.value);
  renderPreviewNow();
};

/* ── Кастомные эмодзи: пикер из сохранённых через бота ── */
interface EmojiGroup { id: string; name: string; emojis: EmojiRef[] }

/* кнопка одного эмодзи: кастомный — картинка по id, стандартный — символ.
   Живёт вне EmojiButton: компонент, объявленный внутри рендера, менял бы
   тип на каждый setState — React пересоздавал бы кнопки, а клик по
   удалённому узлу Dropdown принимал за «клик вне» и закрывал пикер. */
function EmBtn({ e, pick }: { e: EmojiRef; pick: (e: EmojiRef) => void }) {
  return (
    <button className="em" title={e.alt} onClick={() => pick(e)}>
      {e.emoji_id
        ? <img src={`api/emoji/img?id=${e.emoji_id}`} alt={e.alt} loading="lazy"
            onError={(ev) => ev.currentTarget.closest('button')?.remove()} />
        : <span className="uni">{e.alt}</span>}
    </button>
  );
}

export function EmojiButton() {
  const btnRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [groups, setGroups] = useState<EmojiGroup[]>([]);
  const [recent, setRecent] = useState<EmojiRef[]>([]);

  const toggle = async () => {
    if (open) { setOpen(false); return; }
    const resp = await api('/api/emojis');
    const gr = (resp.ok && (resp.groups as EmojiGroup[])) || [];
    setGroups(gr);
    // кастомные эмодзи удалённых паков выпадают и из «Последних»
    const alive = new Set(gr.flatMap((g) => g.emojis.map((e) => e.emoji_id)));
    setRecent(pruneRecent((e) => !e.emoji_id || alive.has(e.emoji_id)));
    setOpen(true);
  };

  /* пикер не закрывается: можно вставить несколько эмодзи подряд;
     закрытие — кнопкой пикера или кликом вне меню (Dropdown) */
  const pick = (e: EmojiRef) => {
    setRecent(pushRecent(e));
    // кастомный — rich-синтаксис, стандартный — просто символ в текст
    insert(e.emoji_id ? `![${e.alt}](tg://emoji?id=${e.emoji_id})` : e.alt, '', '');
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
        {recent.length > 0 && (
          <span style={{ display: 'contents' }}>
            <div className="egroup">Последние</div>
            {recent.map((e) => <EmBtn key={'recent-' + emojiKey(e)} e={e} pick={pick} />)}
          </span>
        )}
        {/* кастомные паки — всегда выше стандартных */}
        {groups.length ? (
          groups.map((g, gi) => (
            <span key={g.id} style={{ display: 'contents' }}>
              {g.name
                ? <div className="egroup">{g.name}</div>
                : groups.length > 1 && <div className="egroup">Без группы</div>}
              {g.emojis.map((e) => <EmBtn key={emojiKey(e) + gi} e={e} pick={pick} />)}
            </span>
          ))
        ) : (
          <div className="emoji-hint">
            Кастомных коллекций пока нет. В боте: /emoji → «Добавить паки» →
            пришлите сообщение с кастомными эмодзи — их паки добавятся целиком.
          </div>
        )}
        {standardEmojis(maxEmojiVersion()).map((cat) => (
          <span key={cat.name} style={{ display: 'contents' }}>
            <div className="egroup">{cat.name}</div>
            {cat.chars.map((ch) => <EmBtn key={ch} e={{ alt: ch }} pick={pick} />)}
          </span>
        ))}
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

/* ── AI-помощник: локальная модель через сервер (/api/ai → Ollama) ── */
export function AiButton() {
  const btnRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const busy = useAi((s) => s.busy);

  const withSel = (fn: (md: HTMLTextAreaElement, s: number, e: number) => void) => {
    setOpen(false);
    const md = getEditorEl();
    if (md) fn(md, md.selectionStart, md.selectionEnd);
  };

  const rewrite = () => withSel((md, s, e) => {
    if (s === e) { toast('Выделите текст, который нужно переписать', true); return; }
    void runAI('rewrite', md.value.slice(s, e), s, e);
  });

  const format = () => withSel((md, s, e) => {
    const hasSel = s !== e;
    const text = hasSel ? md.value.slice(s, e) : md.value;
    if (!text.trim()) { toast('Пост пустой — оформлять нечего', true); return; }
    void runAI('format', text, hasSel ? s : 0, hasSel ? e : md.value.length);
  });

  const generate = () => withSel((_md, s, e) => {
    const q = prompt('О чём написать пост?');
    if (!q || !q.trim()) return;
    void runAI('generate', q.trim(), s, e);
  });

  return (
    <span className="group ai-group">
      <span className="media-wrap">
        <button ref={btnRef} id="aiBtn" title="AI-помощник"
          className={busy ? 'ai-busy' : ''}
          onClick={() => setOpen((o) => !o)}>
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9z"/></svg>
        </button>
        <Dropdown anchorRef={btnRef} open={open} onClose={() => setOpen(false)}>
          <button onClick={rewrite}>Переписать выделенное</button>
          <button onClick={format}>Оформить разметкой</button>
          <button onClick={generate}>Написать с нуля…</button>
        </Dropdown>
      </span>
    </span>
  );
}
