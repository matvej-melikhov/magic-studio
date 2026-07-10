/* localStorage общий на весь origin, а стенды живут на /dev и /prod одного
   хоста — поэтому каждый ключ получает префикс своего стенда, иначе логин
   и черновики стендов затирали бы друг друга (порт LS_SEG из editor.html) */
const LS_SEG = location.pathname.split('/')[1] || '';
const LS_PREFIX = LS_SEG === 'dev' || LS_SEG === 'prod' ? LS_SEG + ':' : '';

export const lsStore = {
  get: (k: string): string | null => localStorage.getItem(LS_PREFIX + k),
  set: (k: string, v: string): void => localStorage.setItem(LS_PREFIX + k, v),
  del: (k: string): void => localStorage.removeItem(LS_PREFIX + k),
};
