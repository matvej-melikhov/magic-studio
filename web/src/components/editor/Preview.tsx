import { useEffect, useRef } from 'react';
import { mathStore, buildContentHtml, applyMath } from '../../lib/preview';
import { getEditorEl } from '../../lib/insert';
import { onPreview, renderPreviewNow } from '../../lib/previewBus';

/* Предпросмотр рендерится через innerHTML (не JSX): вывод рендерера
   содержит инлайн-обработчики (спойлеры) и кастомные виджеты, а сам
   рендерер — дословный порт, менять его форму нельзя. */
export default function Preview() {
  const chatRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const render = () => {
      const chat = chatRef.current;
      if (!chat) return;
      mathStore.length = 0;
      const src = getEditorEl()?.value ?? '';
      const html = buildContentHtml(src) ||
        '<div class="empty">Пост пустой — начните писать слева</div>';
      const time = new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
      chat.innerHTML = `<div class="msg"><div class="bubble"><div class="content">${html}</div>` +
        `<span class="meta"><svg width="15" height="10" viewBox="0 0 22 14" fill="currentColor"><path d="M11 0C6 0 1.7 2.9 0 7c1.7 4.1 6 7 11 7s9.3-2.9 11-7c-1.7-4.1-6-7-11-7zm0 11.7a4.7 4.7 0 110-9.4 4.7 4.7 0 010 9.4zM11 4a3 3 0 100 6 3 3 0 000-6z"/></svg> 2.4K &nbsp;${time}</span></div></div>`;
      applyMath(chat);
    };
    const off = onPreview(render);
    render();                      // первый рендер при открытии редактора
    /* KaTeX грузится с CDN с defer — перерисуем формулы, когда доедет */
    window.addEventListener('load', renderPreviewNow);
    return () => {
      off();
      window.removeEventListener('load', renderPreviewNow);
    };
  }, []);

  return <div id="chat" ref={chatRef} />;
}
