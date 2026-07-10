import { describe, it, expect, beforeEach } from 'vitest';
import { buildContentHtml, inline, mathStore } from './preview';

/* Плейсхолдер формулы в выводе рендерера: U+E000 + индекс + U+E001 */
const ph = (i: number) => '\uE000' + i + '\uE001';

/* Фикстура покрывает все возможности разметки. Если снапшот падает,
   значит порт разошёлся с editor.html — чинить порт, не снапшот. */
const FIXTURE = `# Заголовок H1
###### Заголовок H6

Абзац с **жирным**, __жирным__, *курсивом*, _курсивом_, ~~зачёркнутым~~,
==маркером==, ||спойлером||, \`кодом\` и [ссылкой](https://example.com).

<u>подчёркнутый</u> <s>тег</s> <sub>под</sub> <sup>над</sup> <mark>марк</mark>
<ins>инс</ins> <em>эм</em> <strong>стронг</strong>
<tg-spoiler>тег-спойлер</tg-spoiler>

> Цитата строка 1
> строка 2
>
> новый абзац цитаты

- пункт списка
- ещё пункт
1. нумерованный
2) со скобкой
- [ ] чекбокс пустой
- [x] чекбокс отмеченный

---

\`\`\`python
print('код')
\`\`\`

\`\`\`math
E = mc^2
\`\`\`

$$
x = \\frac{1}{2}
$$

Инлайн формула $a^2+b^2$ в тексте.

| Столбец | Право |
|:--------|------:|
| ячейка  | 123   |

<details><summary>Свёрнуто</summary>
Внутри **rich**-контент
</details>

<details open><summary>Раскрыто</summary>
тело
</details>

<footer>подпись поста</footer>
<aside>выносная цитата<cite>Автор</cite></aside>
<tg-map lat="55.75" long="37.62"/>

<tg-collage>
![](https://a.jpg)
![](https://b.jpg)
</tg-collage>

<tg-slideshow>
![](https://c.jpg)
![](https://d.jpg)
</tg-slideshow>

![подпись](https://img.jpg "Подпись картинки")
![](https://video.mp4)
![](https://sound.mp3)

Эмодзи ![⭐](tg://emoji?id=123456) и сноска[^1] тут.

[^1]: Текст сноски

<a name="anchor"></a>
Ссылка на [якорь](#anchor).`;

describe('buildContentHtml', () => {
  beforeEach(() => {
    mathStore.length = 0;
  });

  it('фикстура целиком совпадает со снапшотом', () => {
    expect(buildContentHtml(FIXTURE)).toMatchSnapshot();
  });

  it('пустой ввод — пустой вывод', () => {
    expect(buildContentHtml('')).toBe('');
  });

  it('формулы уходят в mathStore с PUA-плейсхолдерами', () => {
    const html = buildContentHtml('Текст $x^2$ и блок\n$$y=1$$');
    expect(mathStore).toEqual([['x^2', false], ['y=1', true]]);
    expect(html).toContain(ph(0));
    expect(html).toContain(ph(1));
  });

  it('таблица с выравниванием', () => {
    const html = buildContentHtml('| а | б |\n|:-:|--:|\n| в | г |');
    expect(html).toContain('text-align:center');
    expect(html).toContain('text-align:right');
  });

  it('details парсится рекурсивно', () => {
    const html = buildContentHtml('<details><summary>t</summary>\n**жирный**\n</details>');
    expect(html).toContain('<div class="dbody"><p><b>жирный</b></p></div>');
    expect(html).not.toContain('open');
  });
});

describe('inline', () => {
  beforeEach(() => {
    mathStore.length = 0;
  });

  it('экранирует HTML, но пропускает белый список тегов', () => {
    expect(inline('<script>x</script>')).toBe('&lt;script&gt;x&lt;/script&gt;');
    expect(inline('<b>ж</b>')).toBe('<b>ж</b>');
  });

  it('кастомные эмодзи → img через прокси с fallback на alt', () => {
    const h = inline('![⭐](tg://emoji?id=42)');
    expect(h).toContain('src="api/emoji/img?id=42"');
    expect(h).toContain('alt="⭐"');
  });

  it('обычная разметка', () => {
    expect(inline('**b** _i_ ~~s~~ ==m== \`c\`')).toBe(
      '<b>b</b> <i>i</i> <s>s</s> <mark>m</mark> <code>c</code>');
  });
});
