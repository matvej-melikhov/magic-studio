/* Инлайн-предпросмотр поста в списках. До фазы 2 (порт рендерера
   buildContentHtml) показывает сырой markdown; после — точный рендер. */
export default function InlinePreview({ markdown }: { markdown: string }) {
  return (
    <div className="sched-preview">
      <div className="bubble">
        <div className="content">
          {markdown
            ? <pre style={{ whiteSpace: 'pre-wrap', font: 'inherit', margin: 0 }}>{markdown}</pre>
            : <div className="empty">Пост пустой</div>}
        </div>
      </div>
    </div>
  );
}
