import { create } from 'zustand';

interface ToastState {
  text: string;
  isError: boolean;
  visible: boolean;
  show: (text: string, isError?: boolean) => void;
}

let timer: ReturnType<typeof setTimeout>;

export const useToast = create<ToastState>((set) => ({
  text: '',
  isError: false,
  visible: false,
  show: (text, isError = false) => {
    set({ text, isError, visible: true });
    clearTimeout(timer);
    timer = setTimeout(() => set({ visible: false }), 3500);
  },
}));

/* Для вызова вне React-компонентов (сторы, api) */
export const toast = (text: string, isError = false): void =>
  useToast.getState().show(text, isError);
