import { useEffect, useRef } from 'react';
import { mathStore, buildContentHtml, applyMath } from '../../lib/preview';

/* Инлайн-предпросмотр поста в списках: тот же дословно портированный
   рендерер, что и в редакторе (innerHTML + KaTeX + медиа-виджеты) */
export default function InlinePreview({ markdown }: { markdown: string }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const box = ref.current;
    if (!box) return;
    mathStore.length = 0;
    box.innerHTML = '<div class="bubble"><div class="content">' +
      (buildContentHtml(markdown) || '<div class="empty">Пост пустой</div>') +
      '</div></div>';
    applyMath(box);
  }, [markdown]);

  return <div className="sched-preview" ref={ref} />;
}
