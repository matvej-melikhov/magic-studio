/* Шина обновления предпросмотра: textarea и кнопки просят перерисовку,
   Preview-компонент подписывается. Дебаунс 250 мс как в editor.html. */

const listeners = new Set<() => void>();
let timer: ReturnType<typeof setTimeout>;

export function schedulePreview(delay = 250): void {
  clearTimeout(timer);
  timer = setTimeout(renderPreviewNow, delay);
}

export function renderPreviewNow(): void {
  clearTimeout(timer);
  listeners.forEach((f) => f());
}

export function onPreview(f: () => void): () => void {
  listeners.add(f);
  return () => listeners.delete(f);
}
