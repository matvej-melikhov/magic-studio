import type { ReactNode } from 'react';
import { insert, insertBlock, insertLinePrefix, typeText, getEditorEl } from '../../lib/insert';
import { renderPreviewNow } from '../../lib/previewBus';
import { toast } from '../../store/toast';
import { lsStore } from '../../lib/lsStore';

/* Декларативная панель инструментов: порт data-wrap/data-block/data-before/
   data-snippet/data-key из editor.html. Горячие клавиши — в поле key
   (mod = Cmd на маке / Ctrl на остальных), работают в любой раскладке. */

export interface ToolButton {
  title: string;
  label: ReactNode;
  key?: string;
  run: () => void;
}

const sync = () => {
  const md = getEditorEl();
  if (md) lsStore.set('draft', md.value);
  renderPreviewNow();
};

const wrap = (w: string) => () => { insert(w, w, 'текст'); sync(); };
const around = (b: string, a: string) => () => { insert(b, a, 'текст'); sync(); };
const block = (p: string) => () => { insertLinePrefix(p); sync(); };
const snippet = (tpl: string, ph?: string) => () => { insertBlock(tpl, ph); sync(); };

/* Сноска: [^N] в тексте + определение в конце, нумерация автоматическая */
function footnote(): void {
  const md = getEditorEl();
  if (!md) return;
  const used = [...md.value.matchAll(/\[\^(\d+)\]/g)].map((m) => +m[1]);
  const n = used.length ? Math.max(...used) + 1 : 1;
  const pos = md.selectionStart;
  typeText(`[^${n}]`, pos, md.selectionEnd);
  const end = md.value.replace(/\s+$/, '').length;
  typeText(`\n[^${n}]: Текст сноски`, end, md.value.length);
  md.setSelectionRange(pos + `[^${n}]`.length, pos + `[^${n}]`.length);
  sync();
}

/* Якорь + пример ссылки на него */
function anchor(): void {
  const name = prompt('Имя якоря (латиницей, без пробелов):', 'section-1');
  if (!name) return;
  insertBlock(`<a name="${name.trim()}"></a>`, '');
  toast(`Ссылка на якорь: [текст](#${name.trim()})`);
  sync();
}

/* Дата-время в часовом поясе читателя */
function timeStamp(): void {
  const val = prompt('Дата и время (ГГГГ-ММ-ДД ЧЧ:ММ):',
    new Date(Date.now() + 86400e3).toISOString().slice(0, 16).replace('T', ' '));
  if (!val) return;
  const ts = Math.floor(new Date(val.replace(' ', 'T')).getTime() / 1000);
  if (!ts || isNaN(ts)) { toast('Не понял дату', true); return; }
  const label = new Date(ts * 1000).toLocaleString('ru-RU',
    { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  insert(`![${label}](tg://time?unix=${ts}&format=wDT)`, '', '');
  sync();
}

/* Карта по координатам */
function map(): void {
  const coords = prompt('Координаты «широта, долгота» (и опционально зум):', '55.751, 37.618, 14');
  if (!coords) return;
  const [lat, lon, zoom] = coords.split(',').map((s) => s.trim());
  if (!lat || !lon || isNaN(+lat) || isNaN(+lon)) { toast('Нужны два числа через запятую', true); return; }
  insertBlock(`<tg-map lat="${lat}" long="${lon}" zoom="${zoom && !isNaN(+zoom) ? zoom : 14}"/>`, '');
  sync();
}

/* Иконки — как в editor.html: внутренности svg строкой; атрибуты корня
   по умолчанию контурные, fill-вариант передаётся вторым аргументом */
const STROKE: React.SVGProps<SVGSVGElement> = {
  fill: 'none', stroke: 'currentColor', strokeWidth: 1.5, strokeLinecap: 'round',
};
const svg = (paths: string, attrs: React.SVGProps<SVGSVGElement> = STROKE) => (
  <svg viewBox="0 0 16 16" width="16" height="16" {...attrs}
    dangerouslySetInnerHTML={{ __html: paths }} />
);
const FILL: React.SVGProps<SVGSVGElement> = { fill: 'currentColor' };

export const TOOLBAR_GROUPS: ToolButton[][] = [
  [
    { title: 'Заголовок 1', label: 'H1', key: 'mod+alt+1', run: block('# ') },
    { title: 'Заголовок 2', label: 'H2', key: 'mod+alt+2', run: block('## ') },
    { title: 'Заголовок 3', label: 'H3', key: 'mod+alt+3', run: block('### ') },
    { title: 'Заголовок 4', label: 'H4', key: 'mod+alt+4', run: block('#### ') },
    { title: 'Заголовок 5', label: 'H5', key: 'mod+alt+5', run: block('##### ') },
    { title: 'Заголовок 6', label: 'H6', key: 'mod+alt+6', run: block('###### ') },
  ],
  [
    { title: 'Жирный', label: <b>B</b>, key: 'mod+b', run: wrap('**') },
    { title: 'Курсив', label: <i>I</i>, key: 'mod+i', run: wrap('_') },
    { title: 'Зачёркнутый', label: <s>S</s>, key: 'mod+shift+x', run: wrap('~~') },
    { title: 'Подчёркнутый', label: <u>U</u>, key: 'mod+u', run: around('<u>', '</u>') },
    { title: 'Подстрочный', label: 'x₂', key: 'mod+=', run: around('<sub>', '</sub>') },
    { title: 'Надстрочный', label: 'x²', key: 'mod+shift+=', run: around('<sup>', '</sup>') },
    {
      title: 'Маркер', key: 'mod+shift+h', run: wrap('=='),
      label: <mark style={{ background: '#FDE68A', borderRadius: 2, padding: '0 3px', color: '#1C242C' }}>M</mark>,
    },
    {
      title: 'Спойлер — скрытый текст', key: 'mod+shift+p', run: wrap('||'),
      label: svg('<path d="M1.8 8c2.2-3.2 10.2-3.2 12.4 0-2.2 3.2-10.2 3.2-12.4 0z"/><circle cx="8" cy="8" r="1.7"/><line x1="3" y1="13.2" x2="13" y2="2.8"/>'),
    },
    { title: 'Код в строке', label: '</>', key: 'mod+shift+m', run: wrap('`') },
  ],
  [
    {
      title: 'Цитата', run: block('> '),
      label: svg('<path d="M2 3.5h1.8v9H2zM6.5 4.5h7.5v1.6H6.5zM6.5 7.2h7.5v1.6H6.5zM6.5 9.9h5v1.6h-5z"/>', FILL),
    },
    {
      title: 'Выносная цитата с автором',
      run: snippet('<aside>{sel}<cite>Автор</cite></aside>', 'Выносная цитата'),
      label: svg('<path d="M1.5 1.8h13v1.4h-13zM1.5 12.8h13v1.4h-13z"/><text x="8" y="10.6" text-anchor="middle" font-size="9" font-family="Georgia,serif">❝</text>', FILL),
    },
    {
      title: 'Маркированный список', run: block('- '),
      label: svg('<circle cx="3" cy="4.5" r="1.6"/><rect x="6.5" y="3.7" width="8" height="1.6"/><circle cx="3" cy="11.5" r="1.6"/><rect x="6.5" y="10.7" width="8" height="1.6"/>', FILL),
    },
    {
      title: 'Нумерованный список', run: block('1. '),
      label: svg('<text x="1.2" y="6.6" font-size="6.6" font-weight="700">1.</text><rect x="7" y="3.7" width="7.5" height="1.6"/><text x="1.2" y="13.6" font-size="6.6" font-weight="700">2.</text><rect x="7" y="10.7" width="7.5" height="1.6"/>', FILL),
    },
    {
      title: 'Чекбокс', run: block('- [ ] '),
      label: svg('<rect x="1.5" y="4" width="7.5" height="7.5" rx="1.8"/><path d="M3.8 7.9l1.6 1.6 2.7-3.1" stroke-linecap="round" stroke-linejoin="round"/><line x1="11.5" y1="7.8" x2="15" y2="7.8" stroke-linecap="round"/>', { ...STROKE, strokeLinecap: undefined }),
    },
    {
      title: 'Разделитель', run: snippet('---'),
      label: svg('<rect x="4" y="7.2" width="8" height="1.6" rx=".8"/><circle cx="1.8" cy="8" r=".9"/><circle cx="14.2" cy="8" r=".9"/>', FILL),
    },
    {
      title: 'Сноска', run: footnote,
      label: svg('<text x="2" y="13" font-size="11" font-family="Georgia,serif">a</text><text x="9.5" y="7.5" font-size="7" font-weight="700">1</text>', FILL),
    },
    {
      title: 'Футер — мелкий текст внизу поста',
      run: snippet('<footer>{sel}</footer>', 'Подпись поста'),
      label: svg('<rect x="1.8" y="2.2" width="12.4" height="11.6" rx="1.8"/><rect x="4" y="10" width="8" height="1.6" rx=".8" fill="currentColor" stroke="none"/>'),
    },
    {
      title: 'Якорь + ссылка на него', run: anchor,
      label: svg('<circle cx="8" cy="3.5" r="1.8"/><line x1="8" y1="5.3" x2="8" y2="13.5"/><path d="M2.5 9.5c.4 3 2.6 4.5 5.5 4.5s5.1-1.5 5.5-4.5"/><line x1="5.5" y1="7.5" x2="10.5" y2="7.5"/>'),
    },
  ],
  [
    { title: 'Формула в строке', label: <b>$</b>, run: wrap('$') },
    { title: 'Формула блоком', label: <b>$$</b>, run: snippet('$$\n{sel}\n$$', 'E = mc^2') },
    {
      title: 'Блок кода с языком', run: snippet('```python\n{sel}\n```', "print('код')"),
      label: svg('<rect x="1.5" y="2.5" width="13" height="11" rx="1.8"/><path d="M6.2 6.2 4.4 8l1.8 1.8M9.8 6.2 11.6 8 9.8 9.8"/>'),
    },
    {
      title: 'Таблица',
      run: snippet('| Столбец | Столбец |\n|:--------|--------:|\n| ячейка  | ячейка  |'),
      label: svg('<rect x="1.5" y="3" width="13" height="10" rx="1.5"/><line x1="8" y1="3" x2="8" y2="13"/><line x1="1.5" y1="8" x2="14.5" y2="8"/>'),
    },
    {
      title: 'Сворачиваемый блок',
      run: snippet('<details><summary>Заголовок</summary>\n{sel}\n</details>', 'Скрытый текст'),
      label: svg('<path d="M3 5.5 8 10l5-4.5"/><line x1="3" y1="13" x2="13" y2="13"/>', { ...STROKE, strokeWidth: 1.6, strokeLinejoin: 'round' }),
    },
    {
      title: 'Дата-время: покажется в часовом поясе читателя', run: timeStamp,
      label: svg('<circle cx="8" cy="8" r="6.2"/><path d="M8 4.6V8l2.4 1.8"/>'),
    },
  ],
  [
    {
      title: 'Ссылка — выделите текст и нажмите', run: around('[', '](https://)'),
      label: svg('<path d="M6.5 9.5 9.5 6.5"/><path d="M7.5 4.5 9 3a2.8 2.8 0 0 1 4 4l-1.5 1.5"/><path d="M8.5 11.5 7 13a2.8 2.8 0 0 1-4-4l1.5-1.5"/>'),
    },
    {
      title: 'Коллаж из медиа',
      run: snippet('<tg-collage>\n![](https://ссылка-1.jpg)\n![](https://ссылка-2.jpg)\n</tg-collage>'),
      label: svg('<rect x="1.5" y="2.5" width="7.5" height="5" rx="1"/><rect x="10.5" y="2.5" width="4" height="5" rx="1"/><rect x="1.5" y="9" width="4" height="4.5" rx="1"/><rect x="7" y="9" width="7.5" height="4.5" rx="1"/>', FILL),
    },
    {
      title: 'Слайдшоу',
      run: snippet('<tg-slideshow>\n![](https://ссылка-1.jpg)\n![](https://ссылка-2.jpg)\n</tg-slideshow>'),
      label: svg('<rect x="3.5" y="3" width="9" height="8" rx="1.2"/><line x1="1" y1="5" x2="1" y2="9"/><line x1="15" y1="5" x2="15" y2="9"/><circle cx="6.5" cy="13.8" r=".9" fill="currentColor" stroke="none"/><circle cx="9.5" cy="13.8" r=".9" fill="currentColor" stroke="none" opacity=".45"/>'),
    },
    { title: 'Карта по координатам', run: map,
      label: svg('<path d="M8 14s4.8-4.2 4.8-8A4.8 4.8 0 0 0 3.2 6c0 3.8 4.8 8 4.8 8z" stroke-linejoin="round"/><circle cx="8" cy="6" r="1.6"/>') },
  ],
];

/* Горячие клавиши: e.code не зависит от раскладки и от символов,
   которые даёт Alt на маке */
const isMac = /Mac|iPhone|iPad/.test(navigator.platform);
const hotkeyMap = new Map<string, ToolButton>();
for (const group of TOOLBAR_GROUPS)
  for (const b of group)
    if (b.key) hotkeyMap.set(b.key, b);

export function hotkeyLabel(key: string): string {
  return key.split('+').map((p) =>
    p === 'mod' ? (isMac ? '⌘' : 'Ctrl')
    : p === 'alt' ? (isMac ? '⌥' : 'Alt')
    : p === 'shift' ? (isMac ? '⇧' : 'Shift')
    : p.toUpperCase(),
  ).join(isMac ? '' : '+');
}

export function handleHotkey(e: React.KeyboardEvent): boolean {
  if (!(e.metaKey || e.ctrlKey) || (e.metaKey && e.ctrlKey)) return false;
  const key = e.code.startsWith('Key') ? e.code.slice(3).toLowerCase()
    : e.code.startsWith('Digit') ? e.code.slice(5)
    : e.code === 'Equal' ? '=' : '';
  if (!key) return false;
  const combo = 'mod' + (e.altKey ? '+alt' : '') + (e.shiftKey ? '+shift' : '') + '+' + key;
  const btn = hotkeyMap.get(combo);
  if (btn) { e.preventDefault(); btn.run(); return true; }
  return false;
}
