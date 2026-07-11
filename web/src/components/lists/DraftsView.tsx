import { useNavigate } from 'react-router-dom';
import { useAppState } from '../../store/appState';
import { useEditor } from '../../store/editor';
import { api } from '../../api/client';
import { fmtDate } from '../../lib/format';

export default function DraftsView() {
  const { drafts, refresh } = useAppState();
  const loadDraft = useEditor((s) => s.loadDraft);
  const navigate = useNavigate();

  const open = (id: string) => {
    const d = drafts.find((x) => x.id === id);
    if (!d) return;
    loadDraft(d.id, d.markdown);
    navigate('/editor');
  };

  const remove = async (id: string) => {
    if (!confirm('Удалить черновик?')) return;
    await api('/api/drafts/delete', { id });
    void refresh();
  };

  return (
    <section className="view active" id="view-drafts">
      <div className="page">
        <h2>Черновики</h2>
        <div id="draftsList">
          {!drafts.length ? (
            <div className="empty-state">
              Черновиков нет.<br />
              Напишите пост в редакторе и нажмите «Сохранить черновик».
            </div>
          ) : (
            drafts.map((d) => (
              <div key={d.id} className="card link" onClick={() => open(d.id)}>
                <div className="body">
                  <div className="title">{d.title}</div>
                  <div className="meta">{fmtDate(d.updated)}</div>
                </div>
                <button className="del"
                  onClick={(e) => { e.stopPropagation(); void remove(d.id); }}>
                  Удалить
                </button>
              </div>
            ))
          )}
        </div>
      </div>
    </section>
  );
}
