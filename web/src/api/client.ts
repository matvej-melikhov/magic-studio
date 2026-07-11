import { lsStore } from '../lib/lsStore';

export interface ApiResp {
  ok: boolean;
  error?: string;
  [key: string]: unknown;
}

/* Открытие окна логина по 401 — регистрируется сессионным стором,
   чтобы не тянуть зависимость стора в клиент */
let onAuthRequired: (() => void) | null = null;
export function setAuthHandler(fn: () => void): void {
  onAuthRequired = fn;
}

/* Порт api() из editor.html: относительные пути (стенд может жить под
   префиксом /dev/ за прокси), X-Session, 401 → окно входа */
export async function api(url: string, body?: unknown): Promise<ApiResp> {
  const headers: Record<string, string> = { 'X-Session': lsStore.get('session') || '' };
  url = url.replace(/^\//, '');
  try {
    const r = await fetch(url, body === undefined ? { headers } : {
      method: 'POST',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const resp = await r.json();
    if (r.status === 401) {
      onAuthRequired?.();
      return { ok: false, error: 'Нужен вход' };
    }
    return resp;
  } catch {
    return { ok: false, error: 'Сервер недоступен' };
  }
}
