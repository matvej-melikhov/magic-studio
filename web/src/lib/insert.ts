/* Вставки в textarea редактора. Порт из editor.html.
   Вставка через execCommand — попадает в нативную историю отмены,
   поэтому Ctrl+Z / Cmd+Z отменяет и кнопки панели, и набор текста.
   execCommand устарел, но это единственный кроссбраузерный способ
   сохранить undo — textarea намеренно неконтролируемый. */

let md: HTMLTextAreaElement | null = null;

export function setEditorEl(el: HTMLTextAreaElement | null): void {
  md = el;
}
export function getEditorEl(): HTMLTextAreaElement | null {
  return md;
}

export function typeText(text: string, selStart: number, selEnd: number): void {
  if (!md) return;
  md.focus();
  md.setSelectionRange(selStart, selEnd);
  document.execCommand('insertText', false, text);
}

export function insert(before: string, after: string, placeholder?: string): void {
  if (!md) return;
  const s = md.selectionStart, e = md.selectionEnd;
  const sel = md.value.slice(s, e) || placeholder || '';
  typeText(before + sel + after, s, e);
  md.selectionStart = s + before.length;
  md.selectionEnd = s + before.length + sel.length;
}

/* Блочная вставка: с новой строки, один перенос в конце, выделение
   оборачивается в блок ({sel}), без пустых строк вокруг и внутри */
export function insertBlock(tpl: string, ph?: string): void {
  if (!md) return;
  const s = md.selectionStart, e = md.selectionEnd;
  const sel = md.value.slice(s, e) || ph || '';
  const body = tpl.includes('{sel}') ? tpl.replace('{sel}', sel) : tpl;
  const prefix = s > 0 && md.value[s - 1] !== '\n' ? '\n' : '';
  typeText(prefix + body + '\n', s, e);
  const idx = tpl.indexOf('{sel}');
  if (idx !== -1) {
    const start = s + prefix.length + idx;
    md.selectionStart = start;
    md.selectionEnd = start + sel.length;
  }
}

export function insertLinePrefix(block: string): void {
  if (!md) return;
  const pos = md.selectionStart;
  const lineStart = md.value.lastIndexOf('\n', pos - 1) + 1;
  typeText(block, lineStart, lineStart);
  const shift = block.length;
  md.setSelectionRange(pos + shift, pos + shift);
}
