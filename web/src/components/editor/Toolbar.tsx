import { useState } from 'react';
import { TOOLBAR_GROUPS, hotkeyLabel } from './toolbarConfig';
import { lsStore } from '../../lib/lsStore';

/* Свёрнутая панель: видна первая строка, остальное по стрелке.
   Классы .toolbar/.group/#toolsToggle — из editor.html. */
export default function Toolbar() {
  const [open, setOpen] = useState(lsStore.get('toolsOpen') === '1');

  const toggle = () => {
    setOpen((o) => {
      lsStore.set('toolsOpen', o ? '0' : '1');
      return !o;
    });
  };

  return (
    <div className={'toolbar' + (open ? ' open' : '')}>
      {TOOLBAR_GROUPS.map((group, gi) => (
        <span className="group" key={gi}>
          {group.map((b, bi) => (
            <button key={bi}
              title={b.title + (b.key ? ` — ${hotkeyLabel(b.key)}` : '')}
              onClick={b.run}>
              {b.label}
            </button>
          ))}
        </span>
      ))}
      <button id="toolsToggle" title="Показать все инструменты" onClick={toggle}>
        <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6l5 5 5-5"/></svg>
      </button>
    </div>
  );
}
