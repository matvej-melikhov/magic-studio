import { useEffect, useLayoutEffect, useRef, type ReactNode, type RefObject } from 'react';
import { createPortal } from 'react-dom';

/* Выпадающие меню тулбара живут в body, а не в тулбаре: скролл-контейнер
   (overflow-x: auto, на iOS ещё и -webkit-overflow-scrolling) обрезает
   выпадающие элементы, включая position: fixed. Позиция считается от
   кнопки при открытии — порт toggleDropdown из editor.html. */
export default function Dropdown({ anchorRef, open, onClose, className, children }: {
  anchorRef: RefObject<HTMLElement>;
  open: boolean;
  onClose: () => void;
  className?: string;
  children: ReactNode;
}) {
  const menuRef = useRef<HTMLSpanElement>(null);

  useLayoutEffect(() => {
    if (!open || !menuRef.current || !anchorRef.current) return;
    const menu = menuRef.current;
    const r = anchorRef.current.getBoundingClientRect();
    menu.style.position = 'fixed';
    menu.style.top = r.bottom + 6 + 'px';
    menu.style.left = Math.max(8, Math.min(r.left,
      window.innerWidth - menu.offsetWidth - 8)) + 'px';
  }, [open, anchorRef]);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      const t = e.target as Element;
      /* Клик по кнопке внутри меню, которая перерисовкой уже убрана из DOM
         (меню сменило экран): React успевает обновить дерево до того, как
         клик всплывёт сюда, и contains() дал бы false — это не клик снаружи. */
      if (!t.isConnected) return;
      if (!menuRef.current?.contains(t) && !anchorRef.current?.contains(t)) onClose();
    };
    document.addEventListener('click', close);
    return () => document.removeEventListener('click', close);
  }, [open, onClose, anchorRef]);

  if (!open) return null;
  return createPortal(
    <span className={'media-menu' + (className ? ' ' + className : '')} ref={menuRef}>
      {children}
    </span>,
    document.body,
  );
}
