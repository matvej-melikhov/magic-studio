import { useState } from 'react';
import Toolbar from './Toolbar';
import MarkdownTextarea from './MarkdownTextarea';
import Preview from './Preview';
import EditorFoot from './EditorFoot';
import StyleGuideTour from './StyleGuideTour';
import { useEditor } from '../../store/editor';
import { getEditorEl } from '../../lib/insert';
import { renderPreviewNow } from '../../lib/previewBus';
import { useTour } from '../../store/tour';

/* Кнопка гида по стилям — рядом с заголовком «Разметка» */
function GuideButton() {
  const start = useTour((s) => s.start);
  return (
    <button id="guideBtn" title="Гид по стилям" onClick={start}>
      <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9"/><path d="M9.2 9a2.9 2.9 0 015.6 1c0 1.9-2.8 2.2-2.8 3.6"/><circle cx="12" cy="17.2" r=".6" fill="currentColor" stroke="none"/></svg>
    </button>
  );
}

export default function EditorView() {
  const { draftState, editingSched, editingPub, newPost, stopAllEditing, loadTick } = useEditor();
  const [showPreview, setShowPreview] = useState(false);

  const onNewPost = () => {
    const md = getEditorEl();
    if (!md) return;
    if (md.value.trim() && !confirm('Очистить редактор? Несохранённый текст пропадёт.')) return;
    md.value = '';
    newPost();
    renderPreviewNow();
    md.focus();
  };

  const cancelEditing = (e: React.MouseEvent) => {
    e.preventDefault();
    stopAllEditing();
  };

  return (
    <section className="view active" id="view-editor">
      <div className="mseg" id="mseg">
        <button className={showPreview ? '' : 'on'} onClick={() => setShowPreview(false)}>
          Разметка
        </button>
        <button className={showPreview ? 'on' : ''}
          onClick={() => { setShowPreview(true); renderPreviewNow(); }}>
          Предпросмотр
        </button>
      </div>
      <div className={'workspace' + (showPreview ? ' show-preview' : '')} id="workspace">
        <div className="pane editor-pane">
          <div className="pane-h">Разметка
            <GuideButton />
            <span className="spacer"></span>
            <span id="draftState" style={{ textTransform: 'none', letterSpacing: 0, fontWeight: 500 }}>
              {draftState}
              {(editingSched || editingPub) && (
                <> · <a href="#" onClick={cancelEditing}>отменить</a></>
              )}
            </span>
            <button className="tg-btn" id="newPostBtn"
              title="Очистить редактор и начать новый пост" onClick={onNewPost}>
              + Новый пост
            </button>
          </div>
          <Toolbar />
          <MarkdownTextarea key={loadTick} />
          <EditorFoot />
        </div>
        <div className="pane preview-pane">
          <div className="pane-h">Предпросмотр
            <span className="spacer"></span>
            <TgPreviewButton />
          </div>
          <Preview />
        </div>
      </div>
      <StyleGuideTour />
    </section>
  );
}

import { api } from '../../api/client';
import { toast } from '../../store/toast';

function TgPreviewButton() {
  const [busy, setBusy] = useState(false);
  const send = async () => {
    const md = getEditorEl();
    if (!md?.value.trim()) { toast('Пост пустой', true); return; }
    setBusy(true);
    const resp = await api('/api/preview', { markdown: md.value });
    setBusy(false);
    toast(resp.ok ? 'Превью отправлено в чат с ботом' : resp.error || 'Ошибка', !resp.ok);
  };
  return (
    <button className="tg-btn" id="tgPreviewBtn" disabled={busy} onClick={() => void send()}>
      <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M23.9 3.4c.2-1.2-1-2.2-2.1-1.7L1.4 10.2c-1.2.5-1.1 2.3.2 2.6l5.5 1.4 2.1 6.6c.4 1.1 1.8 1.4 2.6.5l3-3.3 5.5 4c1 .8 2.5.2 2.7-1.1zM8.8 13.6l9.4-7.7c.3-.2.6.2.4.5l-7.6 8.5-.3 3.4z"/></svg>
      {' '}Превью в TG
    </button>
  );
}
