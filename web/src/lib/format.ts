export const fmtDate = (ts: number): string =>
  new Date(ts * 1000).toLocaleString('ru-RU',
    { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });

export function countdownText(when: number): string {
  const left = Math.max(0, when - Math.floor(Date.now() / 1000));
  const h = Math.floor(left / 3600), m = Math.floor((left % 3600) / 60), s = left % 60;
  return [h, m, s].map((x) => String(x).padStart(2, '0')).join(':');
}
