import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAppState, type SchedPost, type PubPost } from '../../store/appState';
import { useEditor } from '../../store/editor';
import { api } from '../../api/client';
import { toast } from '../../store/toast';
import { fmtDate, countdownText } from '../../lib/format';
import { lsStore } from '../../lib/lsStore';
import InlinePreview from './InlinePreview';

const BADGES: Record<string, string> = { pending: 'ожидает', sending: 'отправка…', error: 'ошибка' };

function copyText(t: string): void {
  /* clipboard API недоступен на http:// (не-secure context) — фолбэк
     через скрытую textarea и execCommand */
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(t).then(
      () => toast('Ссылка скопирована'),
      () => toast('Не удалось скопировать', true));
    return;
  }
  const ta = document.createElement('textarea');
  ta.value = t;
  ta.style.cssText = 'position:fixed;opacity:0';
  document.body.appendChild(ta);
  ta.select();
  try {
    const ok = document.execCommand('copy');
    toast(ok ? 'Ссылка скопирована' : 'Не удалось скопировать', !ok);
  } catch {
    toast('Не удалось скопировать', true);
  }
  ta.remove();
}

/* Секундный тик для отсчётов; после нуля подтягиваем статус с сервера */
function useCountdownTick(scheduled: SchedPost[], refresh: () => Promise<void>) {
  const [, setTick] = useState(0);
  useEffect(() => {
    let overdueRefresh = 0;
    const t = setInterval(() => {
      setTick((x) => x + 1);
      const anyOverdue = scheduled.some(
        (p) => p.status === 'pending' && p.when <= Date.now() / 1000);
      if (anyOverdue && Date.now() - overdueRefresh > 5000) {
        overdueRefresh = Date.now();
        void refresh();
      }
    }, 1000);
    return () => clearInterval(t);
  }, [scheduled, refresh]);
}

export default function ScheduledView() {
  const { channels, scheduled, published, refresh } = useAppState();
  const { startEditingSched, startEditingPub } = useEditor();
  const navigate = useNavigate();
  const [filter, setFilter] = useState(lsStore.get('schedFilter') || '');
  const [shown, setShown] = useState(10);
  const [openPreview, setOpenPreview] = useState<string | null>(null);
  const [linkMenu, setLinkMenu] = useState<{ url: string; x: number; y: number } | null>(null);

  useCountdownTick(scheduled, refresh);

  /* Закрытие меню ссылки кликом мимо */
  useEffect(() => {
    if (!linkMenu) return;
    const close = () => setLinkMenu(null);
    document.addEventListener('click', close);
    return () => document.removeEventListener('click', close);
  }, [linkMenu]);

  if (!scheduled.length && !published.length) {
    return (
      <section className="view active" id="view-scheduled">
        <div className="page">
          <h2>Посты</h2>
          <div className="empty-state">
            Отложенных постов нет.<br />
            В редакторе нажмите «Опубликовать» → «По времени» — сервер опубликует
            пост сам (компьютер с сервером должен работать в этот момент).
          </div>
        </div>
      </section>
    );
  }

  // селектор канала: подключённые + встречающиеся в данных
  const targets = [...new Set([
    ...channels.map((c) => c.username),
    ...scheduled.map((p) => p.target),
    ...published.map((p) => p.target),
  ])];
  const activeFilter = targets.includes(filter) ? filter : '';
  const schedFiltered = scheduled.filter((p) => !activeFilter || p.target === activeFilter);
  const pubFiltered = published.filter((p) => !activeFilter || p.target === activeFilter);

  const changeFilter = (v: string) => {
    setFilter(v);
    lsStore.set('schedFilter', v);
    setShown(10);
  };

  const cancel = async (id: string) => {
    if (!confirm('Отменить отложенный пост?')) return;
    await api('/api/schedule/cancel', { id });
    void refresh();
  };

  const editSched = (post: SchedPost) => {
    startEditingSched(post);
    navigate('/editor');
  };
  const editPub = (post: PubPost) => {
    startEditingPub(post);
    navigate('/editor');
  };

  const togglePreview = (key: string) =>
    setOpenPreview((cur) => (cur === key ? null : key));

  return (
    <section className="view active" id="view-scheduled">
      <div className="page">
        <h2>Посты</h2>
        <div id="scheduledList">
          <select className="sched-filter" value={activeFilter}
            onChange={(e) => changeFilter(e.target.value)}>
            <option value="">Все каналы</option>
            {targets.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>

          {schedFiltered.length > 0 && <div className="section-h">Отложено</div>}
          {schedFiltered.map((p) => (
            <div key={p.id}>
              <div className="card sched">
                <div className="body" onClick={() => togglePreview('s' + p.id)}>
                  <div className="title">
                    {p.markdown.split('\n')[0].replace(/^#+\s*/, '').slice(0, 60) || '(пусто)'}
                  </div>
                  <div className="meta">
                    {p.target} · {fmtDate(p.when)}{p.error ? ' · ' + p.error : ''}
                  </div>
                </div>
                {p.status === 'pending'
                  ? <span className="countdown">{countdownText(p.when)}</span>
                  : <span className={`badge ${p.status === 'sending' ? 'pending' : p.status}`}>
                      {BADGES[p.status] || p.status}
                    </span>}
                {p.status !== 'sending' && (
                  <>
                    <button className="edit" onClick={() => editSched(p)}>Изменить</button>
                    <button className="del" onClick={() => void cancel(p.id)}>Отменить</button>
                  </>
                )}
              </div>
              {openPreview === 's' + p.id && <InlinePreview markdown={p.markdown} />}
            </div>
          ))}

          {pubFiltered.length > 0 && <div className="section-h">Опубликовано</div>}
          {pubFiltered.slice(0, shown).map((p) => (
            <div key={p.id}>
              <div className="card pub">
                <div className="body"
                  onClick={() => p.markdown && togglePreview('p' + p.id)}>
                  <div className="title">{p.title}</div>
                  <div className="meta">{p.target}</div>
                </div>
                <span className="badge published">{fmtDate(p.when)}</span>
                {p.message_id && p.target.startsWith('@') && (
                  <button className="edit iconb" title="Ссылка на пост"
                    onClick={(e) => {
                      e.stopPropagation();
                      const url = `https://t.me/${p.target.slice(1)}/${p.message_id}`;
                      setLinkMenu(linkMenu?.url === url ? null
                        : { url, x: e.clientX, y: e.clientY });
                    }}>
                    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><path d="M15 3h6v6"/><path d="M10 14L21 3"/></svg>
                  </button>
                )}
                {p.message_id && (
                  <button className="edit iconb" title="Изменить пост"
                    onClick={() => editPub(p)}>
                    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z"/></svg>
                  </button>
                )}
              </div>
              {openPreview === 'p' + p.id && <InlinePreview markdown={p.markdown} />}
            </div>
          ))}
          {pubFiltered.length > shown && (
            <button className="btn ghost show-more" onClick={() => setShown((s) => s + 10)}>
              Показать ещё ({pubFiltered.length - shown})
            </button>
          )}
        </div>
      </div>

      {linkMenu && (
        <span className="media-menu" id="linkMenu"
          style={{ position: 'fixed', left: linkMenu.x, top: linkMenu.y }}>
          <button onClick={() => window.open(linkMenu.url, '_blank', 'noopener')}>
            Открыть в Telegram
          </button>
          <button onClick={() => copyText(linkMenu.url)}>Скопировать ссылку</button>
        </span>
      )}
    </section>
  );
}
