import { VERSION_PROBES } from './standardEmojis';

/* Определение максимальной версии эмодзи, которую умеет рисовать система:
   свежие эмодзи без глифа выглядят квадратом-«тофу», а разорванные
   ZWJ-связки — двумя картинками. Рисуем представителя каждой версии
   на canvas (от новых к старым) и берём первую, что рендерится корректно. */

let cached: number | null = null;

function makeProbe(): ((char: string) => boolean) | null {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 32;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) return null;
  ctx.textBaseline = 'top';
  ctx.font = '24px sans-serif';

  const draw = (s: string): string => {
    ctx.clearRect(0, 0, 32, 32);
    ctx.fillText(s, 0, 0);
    return canvas.toDataURL();
  };
  const baseWidth = ctx.measureText('\u{1F600}').width;   // эталон 😀
  const tofu = draw('\u{10FFFE}');                        // заведомо нет глифа

  return (char: string) => {
    // разорванная связка (ZWJ/флаг) заметно шире одного глифа
    if (ctx.measureText(char).width > baseWidth * 1.3) return false;
    const drawn = draw(char);
    return drawn !== tofu && drawn !== draw('');          // не тофу и не пусто
  };
}

export function maxEmojiVersion(): number {
  if (cached !== null) return cached;
  try {
    const supports = makeProbe();
    if (supports) {
      for (const [version, probe] of VERSION_PROBES) {
        if (supports(probe)) return (cached = version);
      }
    }
  } catch {
    /* canvas недоступен (тесты, экзотика) — не фильтруем */
  }
  return (cached = Infinity);
}
