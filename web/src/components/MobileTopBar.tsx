import { useRef } from 'react';
import LogoMark from './LogoMark';
import { useAppState } from '../store/appState';
import { useSession } from '../store/session';

/* Мобильная шапка (id и классы из editor.html). Диагностика вьюпорта —
   5 тапов по логотипу — сохранена как есть. */
export default function MobileTopBar() {
  const name = useAppState((s) => s.name);
  const logout = useSession((s) => s.logout);
  const taps = useRef({ count: 0, timer: 0 as ReturnType<typeof setTimeout> | 0 });

  const onLogoClick = () => {
    const t = taps.current;
    clearTimeout(t.timer);
    t.timer = setTimeout(() => (t.count = 0), 2000);
    if (++t.count < 5) return;
    t.count = 0;
    const probe = document.createElement('div');
    probe.style.cssText = 'position:fixed;visibility:hidden;' +
      'padding:env(safe-area-inset-top) env(safe-area-inset-right) ' +
      'env(safe-area-inset-bottom) env(safe-area-inset-left)';
    document.body.appendChild(probe);
    const cs = getComputedStyle(probe);
    const nav = document.getElementById('sidebar')!.getBoundingClientRect();
    alert([
      'standalone: ' + matchMedia('(display-mode: standalone)').matches,
      'inner: ' + innerWidth + 'x' + innerHeight,
      'screen: ' + screen.width + 'x' + screen.height,
      'visual: ' + (visualViewport ? Math.round(visualViewport.height) : '—'),
      'inset top/bottom: ' + cs.paddingTop + ' / ' + cs.paddingBottom,
      'nav rect: top ' + Math.round(nav.top) + ', bottom ' + Math.round(nav.bottom),
      'dvh(app): ' + Math.round(document.getElementById('app')!.getBoundingClientRect().height),
    ].join('\n'));
    probe.remove();
  };

  return (
    <div id="mtop">
      <div className="logo" onClick={onLogoClick}><LogoMark size={15} /></div>
      <div className="name">Magic Studio</div>
      <span className="spacer"></span>
      <span id="mtopUser">{name}</span>
      <button id="mtopLogout" title="Выйти из аккаунта" hidden={!name}
        onClick={() => { if (confirm('Выйти из аккаунта?')) logout(); }}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/><path d="M16 17l5-5-5-5"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
      </button>
    </div>
  );
}
