import { create } from 'zustand';
import { api, setAuthHandler } from '../api/client';
import { lsStore } from '../lib/lsStore';
import { toast } from './toast';
import { useAppState } from './appState';

/* Опрос живёт столько же, сколько токен у бота (10 минут), потом
   останавливается — для нового входа кнопка генерирует свежий токен */
const LOGIN_POLL_TTL = 10 * 60 * 1000;

function randomHex(len: number): string {
  /* crypto.randomUUID недоступен на http:// (не-secure context) —
     getRandomValues работает везде */
  const bytes = new Uint8Array(len / 2);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

interface SessionState {
  loginOpen: boolean;
  loginError: string;
  loginWaiting: boolean;
  botLink: string;
  showLogin: () => void;
  logout: () => void;
  finishLogin: (token: string) => void;
  prepareTgLogin: () => Promise<void>;
  startPoll: () => void;
  pollLogin: () => Promise<void>;
  loginWithCode: (code: string) => Promise<void>;
}

let pollTimer: ReturnType<typeof setInterval> | null = null;
let loginToken = '';
let loginStarted = 0;

function stopPoll(set: (p: Partial<SessionState>) => void): void {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
  loginStarted = 0;
  set({ loginWaiting: false });
}

export const useSession = create<SessionState>((set, get) => ({
  loginOpen: false,
  loginError: '',
  loginWaiting: false,
  botLink: '',

  showLogin: () => {
    if (!get().loginOpen) {
      set({ loginOpen: true });
      void get().prepareTgLogin();
    }
  },

  logout: () => {
    lsStore.del('session');
    get().showLogin();
  },

  finishLogin: (token) => {
    stopPoll(set);
    lsStore.set('session', token);
    set({ loginOpen: false, loginError: '' });
    toast('Вы вошли');
    void useAppState.getState().refresh();
  },

  prepareTgLogin: async () => {
    loginToken = 'login-' + randomHex(24);
    const cfg = await api('/api/config');
    if (cfg.ok && cfg.bot) {
      set({ botLink: `https://t.me/${cfg.bot}?start=${loginToken}` });
    } else {
      set({ loginError: 'Сервер недоступен — обновите страницу' });
    }
  },

  startPoll: () => {
    set({ loginError: '', loginWaiting: true });
    if (pollTimer) clearInterval(pollTimer);
    loginStarted = Date.now();
    pollTimer = setInterval(() => void get().pollLogin(), 2000);
  },

  pollLogin: async () => {
    if (!loginStarted || !get().loginOpen) return;
    if (Date.now() - loginStarted > LOGIN_POLL_TTL) {
      stopPoll(set);
      set({ loginError: 'Время входа истекло — нажмите кнопку ещё раз.' });
      void get().prepareTgLogin();
      return;
    }
    const resp = await api('/api/login', { code: loginToken });
    if (resp.ok) get().finishLogin(resp.token as string);
  },

  loginWithCode: async (code) => {
    if (code.length < 6) {
      set({ loginError: 'Введите 6 цифр из чата с ботом' });
      return;
    }
    const resp = await api('/api/login', { code });
    if (resp.ok) get().finishLogin(resp.token as string);
    else set({ loginError: resp.error || 'Не получилось, попробуйте ещё раз' });
  },
}));

/* 401 из любого api-вызова открывает окно входа */
setAuthHandler(() => useSession.getState().showLogin());

/* Safari замораживает таймеры в фоне — проверяем сразу при возврате на вкладку */
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) void useSession.getState().pollLogin();
});
window.addEventListener('focus', () => void useSession.getState().pollLogin());
