import { Fragment, useState } from 'react';
import { TOOLBAR_GROUPS, hotkeyLabel } from './toolbarConfig';
import { EmojiButton, MediaButton, AiButton } from './ToolbarExtras';
import { lsStore } from '../../lib/lsStore';
import { useTour } from '../../store/tour';

/* Свёрнутая панель: видна первая строка, остальное по стрелке.
   Классы .toolbar/.group/#toolsToggle — из editor.html.
   Интерактивные виджеты стоят на местах оригинала: эмодзи — в конце
   группы инлайн-стилей (1), медиа — после кнопки ссылки в группе 4,
   AI — отдельной группой в конце.
   data-tour / data-tour-group — якоря для гида по стилям (StyleGuideTour);
   пока гид активен, панель принудительно раскрыта. */
export default function Toolbar() {
  const [open, setOpen] = useState(lsStore.get('toolsOpen') === '1');
  const tour = useTour();

  const toggle = () => {
    setOpen((o) => {
      lsStore.set('toolsOpen', o ? '0' : '1');
      return !o;
    });
  };

  return (
    <div className={'toolbar' + (open || tour.active ? ' open' : '')}>
      {TOOLBAR_GROUPS.map((group, gi) => (
        <span className="group" key={gi} data-tour-group={gi}>
          {group.map((b, bi) => (
            <Fragment key={bi}>
              <button
                data-tour={`${gi}-${bi}`}
                title={b.title + (b.key ? ` — ${hotkeyLabel(b.key)}` : '')}
                onClick={b.run}>
                {b.label}
              </button>
              {gi === 4 && bi === 0 && <MediaButton />}
            </Fragment>
          ))}
          {gi === 1 && <EmojiButton />}
        </span>
      ))}
      <AiButton />
      <button id="toolsToggle" title="Показать все инструменты" onClick={toggle}>
        <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6l5 5 5-5"/></svg>
      </button>
    </div>
  );
}
