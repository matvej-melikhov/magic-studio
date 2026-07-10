import { useEffect, useState } from 'react';
import { useAppState } from '../../store/appState';
import { useEditor } from '../../store/editor';
import { api } from '../../api/client';
import { toast } from '../../store/toast';
import { fmtDate } from '../../lib/format';
import { getEditorEl } from '../../lib/insert';
import { lsStore } from '../../lib/lsStore';

type SheetMode = 'now' | 'later' | 'edit';

const SHEET_CONF: Record<SheetMode, { title: string; ok: string; time: boolean }> = {
  now: { title: 'Опубликовать сейчас', ok: 'Опубликовать', time: false },
  later: { title: 'Отложенная публикация', ok: 'Запланировать', time: true },
  edit: { title: 'Изменить отложенный пост', ok: 'Сохранить', time: true },
};

/* Локальное время для input[type=datetime-local] */
function toLocalInput(d: Date): string {
  const x = new Date(d);
  x.setMinutes(x.getMinutes() - x.getTimezoneOffset());
  return x.toISOString().slice(0, 16);
}

export default function EditorFoot() {
  const { channels, refresh } = useAppState();
  const editor = useEditor();
  const [menuOpen, setMenuOpen] = useState(false);
  const [sheet, setSheet] = useState<SheetMode | null>(null);
  const [target, setTarget] = useState('');
  const [when, setWhen] = useState('');
  const [busy, setBusy] = useState(false);

  /* Клик мимо меню закрывает его — как в editor.html */
  useEffect(() => {
    if (!menuOpen) return;
    const close = (e: MouseEvent) => {
      if (!(e.target as Element).closest('.pub-wrap')) setMenuOpen(false);
    };
    document.addEventListener('click', close);
    return () => document.removeEventListener('click', close);
  }, [menuOpen]);

  const mdValue = () => getEditorEl()?.value ?? '';

  const saveDraft = async () => {
    if (!mdValue().trim()) { toast('Пост пустой', true); return; }
    const resp = await api('/api/drafts/save',
      { id: editor.currentDraftId, markdown: mdValue() });
    if (resp.ok) {
      /* не loadDraft: он ремаунтит textarea и стирает историю Ctrl+Z */
      editor.setCurrentDraftId(resp.id as string);
      editor.setDraftState('сохранено');
      toast('Черновик сохранён');
      void refresh();
    } else toast(resp.error || 'Ошибка', true);
  };

  const openSheet = (mode: SheetMode) => {
    setMenuOpen(false);
    setSheet(mode);
    setTarget(mode === 'edit' && editor.editingSched
      ? editor.editingSched.target : lsStore.get('target') || '');
    const base = mode === 'edit' && editor.editingSched
      ? new Date(editor.editingSched.when * 1000)
      : new Date(Date.now() + 3600 * 1000);
    setWhen(toLocalInput(base));
  };

  const onPublishClick = async () => {
    if (!mdValue().trim()) { toast('Пост пустой', true); return; }
    if (editor.editingPub) {
      if (!confirm('Обновить пост в ' + editor.editingPub.target + '?')) return;
      setBusy(true);
      const resp = await api('/api/published/update',
        { id: editor.editingPub.id, markdown: mdValue() });
      setBusy(false);
      if (resp.ok) {
        toast('Пост обновлён в ' + editor.editingPub.target);
        editor.stopAllEditing();
        void refresh();
      } else toast(resp.error || 'Ошибка', true);
      return;
    }
    if (editor.editingSched) { openSheet('edit'); return; }
    setMenuOpen((o) => !o);
  };

  const onSheetOk = async () => {
    if (!sheet) return;
    if (!target) { toast('Выберите канал', true); return; }
    setBusy(true);
    let resp;
    if (sheet === 'now') {
      resp = await api('/api/publish', { markdown: mdValue(), target });
    } else {
      const ts = Math.floor(new Date(when).getTime() / 1000);
      if (!ts || isNaN(ts)) { toast('Укажите время', true); setBusy(false); return; }
      resp = sheet === 'edit' && editor.editingSched
        ? await api('/api/schedule/update',
            { id: editor.editingSched.id, markdown: mdValue(), target, when: ts })
        : await api('/api/schedule/add', { markdown: mdValue(), target, when: ts });
    }
    setBusy(false);
    setSheet(null);
    if (!resp.ok) { toast(resp.error || 'Ошибка', true); return; }
    if (sheet === 'now') toast('Опубликовано в ' + target);
    else toast((sheet === 'edit' ? 'Изменения сохранены — ' : 'Запланировано — ') +
               fmtDate(Math.floor(new Date(when).getTime() / 1000)));
    if (sheet !== 'now') editor.stopAllEditing();
    void refresh();
  };

  const publishLabel = editor.editingPub
    ? 'Сохранить в ' + editor.editingPub.target
    : editor.editingSched
      ? 'Сохранить изменения'
      : <>Опубликовать <span className="caret">▾</span></>;

  return (
    <>
      <div className="editor-foot">
        <button className="btn ghost" id="saveDraftBtn" onClick={() => void saveDraft()}>
          В черновики
        </button>
        <div className="pub-wrap">
          <button className="btn primary" id="publishBtn" disabled={busy}
            onClick={() => void onPublishClick()}>
            {publishLabel}
          </button>
          <div className="pub-menu" id="pubMenu" hidden={!menuOpen}>
            <button onClick={() => openSheet('now')}>Сразу</button>
            <button onClick={() => openSheet('later')}>По времени</button>
          </div>
        </div>
      </div>

      <div id="sheet" className={sheet ? 'open' : ''}
        onClick={(e) => { if (e.target === e.currentTarget) setSheet(null); }}>
        <div className="panel">
          <h3 id="sheetTitle">{sheet ? SHEET_CONF[sheet].title : ''}</h3>
          <select id="target" value={target}
            onChange={(e) => { setTarget(e.target.value); lsStore.set('target', e.target.value); }}>
            <option value="">Куда публиковать…</option>
            {channels.map((c) => (
              <option key={c.username} value={c.username}>
                {c.title} ({c.username})
              </option>
            ))}
          </select>
          {sheet && SHEET_CONF[sheet].time && (
            <input type="datetime-local" id="scheduleTime" value={when}
              onChange={(e) => setWhen(e.target.value)} />
          )}
          <div className="row">
            <button className="btn ghost" onClick={() => setSheet(null)}>Отмена</button>
            <button className="btn primary" disabled={busy} onClick={() => void onSheetOk()}>
              {sheet ? SHEET_CONF[sheet].ok : ''}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
