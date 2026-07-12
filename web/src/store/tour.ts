import { create } from 'zustand';
import { GUIDE_STEPS } from '../components/editor/guideSteps';

/* Интерактивный гид по кнопкам стилей: вуаль с «дыркой» вокруг текущей
   кнопки и карточка с пояснением. Пока тур активен, панель инструментов
   принудительно раскрыта (Toolbar подписан на active). */
interface TourState {
  active: boolean;
  step: number;
  start: () => void;
  stop: () => void;
  next: () => void;
  prev: () => void;
}

export const useTour = create<TourState>((set, get) => ({
  active: false,
  step: 0,
  start: () => set({ active: true, step: 0 }),
  stop: () => set({ active: false }),
  next: () => {
    const { step } = get();
    if (step + 1 >= GUIDE_STEPS.length) set({ active: false });
    else set({ step: step + 1 });
  },
  prev: () => set((s) => ({ step: Math.max(0, s.step - 1) })),
}));
