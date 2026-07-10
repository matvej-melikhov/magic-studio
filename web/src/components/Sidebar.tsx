import { NavLink } from 'react-router-dom';
import { useAppState } from '../store/appState';
import { useSession } from '../store/session';
import { lsStore } from '../lib/lsStore';

/* id и классы совпадают с editor.html — CSS перенесён дословно.
   Вместо button[data-view] — NavLink: URL меняется без перезагрузки,
   а .active вешает сам роутер. */

const NAV = [
  {
    to: '/editor', title: 'Редактор', cnt: null as null | ((s: ReturnType<typeof useAppState.getState>) => number),
    icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.375 2.625a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4Z"/></svg>,
  },
  {
    to: '/drafts', title: 'Черновики', cnt: (s) => s.drafts.length,
    icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M16 13H8"/><path d="M16 17H8"/></svg>,
  },
  {
    to: '/scheduled', title: 'Посты', cnt: (s) => s.scheduled.filter((p) => p.status === 'pending').length,
    icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/></svg>,
  },
  {
    to: '/channels', title: 'Каналы', cnt: (s) => s.channels.length,
    icon: <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4.9 19.1C1 15.2 1 8.8 4.9 4.9"/><path d="M7.8 16.2c-2.3-2.3-2.3-6.1 0-8.5"/><circle cx="12" cy="12" r="2"/><path d="M16.2 7.8c2.3 2.3 2.3 6.1 0 8.5"/><path d="M19.1 4.9C23 8.8 23 15.2 19.1 19.1"/></svg>,
  },
] as const;

export default function Sidebar({ onToggle }: { onToggle: () => void }) {
  const appState = useAppState();
  const { name } = appState;
  const logout = useSession((s) => s.logout);

  return (
    <aside id="sidebar">
      <div className="brand">
        <div className="logo">Md</div>
        <div className="brand-text">
          <div className="name">Студия постов</div>
          <div className="tag">rich-формат Telegram</div>
        </div>
      </div>
      <button id="sideToggle" title="Свернуть меню" onClick={onToggle}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M15 6l-6 6 6 6"/></svg>
      </button>
      <nav id="mainNav">
        {NAV.map((item) => {
          const n = item.cnt ? item.cnt(appState) : 0;
          return (
            <NavLink key={item.to} to={item.to} title={item.title}
              className={({ isActive }) => (isActive ? 'active' : '')}>
              {item.icon}
              <span className="lbl">{item.title}</span>
              {item.cnt && <span className="cnt">{n || ''}</span>}
            </NavLink>
          );
        })}
      </nav>
      <div className="foot" id="sideFoot">
        {name ? (
          <>Вы вошли как <b>{name}</b> ·{' '}
            <a href="#" onClick={(e) => { e.preventDefault(); logout(); }}>выйти</a></>
        ) : (
          'Публикация через Bot API 10.1 · sendRichMessage'
        )}
      </div>
    </aside>
  );
}

export function applySavedCollapse(): boolean {
  return lsStore.get('sideCollapsed') === '1';
}
