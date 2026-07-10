import { create } from 'zustand';
import { lsStore } from '../lib/lsStore';
import type { SchedPost, PubPost } from './appState';

/* Кросс-разделные флаги редактора: текущий черновик, режимы правки
   отложенного/опубликованного. Сам текст живёт в неконтролируемом
   textarea (см. MarkdownTextarea) и зеркалится в localStorage.
   loadTick — сигнал «текст заменили извне»: по нему EditorView
   ремаунтит textarea (при обычном сохранении ремаунта нет — иначе
   терялась бы нативная история Ctrl+Z). */
interface EditorState {
  currentDraftId: string | null;
  editingSched: SchedPost | null;
  editingPub: PubPost | null;
  draftState: string;               // подпись у заголовка «Разметка»
  loadTick: number;
  setDraftState: (s: string) => void;
  setCurrentDraftId: (id: string) => void;
  loadDraft: (id: string, markdown: string) => void;
  newPost: () => void;
  startEditingSched: (post: SchedPost) => void;
  startEditingPub: (post: PubPost) => void;
  stopAllEditing: () => void;
}

export const useEditor = create<EditorState>((set) => ({
  currentDraftId: lsStore.get('draftId'),
  editingSched: null,
  editingPub: null,
  draftState: '',
  loadTick: 0,

  setDraftState: (s) => set({ draftState: s }),

  setCurrentDraftId: (id) => {
    lsStore.set('draftId', id);
    set({ currentDraftId: id });
  },

  loadDraft: (id, markdown) => {
    lsStore.set('draft', markdown);
    lsStore.set('draftId', id);
    set((st) => ({
      currentDraftId: id, draftState: 'черновик загружен', loadTick: st.loadTick + 1,
    }));
  },

  newPost: () => {
    lsStore.set('draft', '');
    lsStore.del('draftId');
    set((st) => ({
      currentDraftId: null, draftState: '', editingSched: null, editingPub: null,
      loadTick: st.loadTick + 1,
    }));
  },

  startEditingSched: (post) => {
    lsStore.set('draft', post.markdown);
    set((st) => ({
      editingSched: post, editingPub: null, draftState: 'правка отложенного',
      loadTick: st.loadTick + 1,
    }));
  },

  startEditingPub: (post) => {
    lsStore.set('draft', post.markdown);
    set((st) => ({
      editingPub: post, editingSched: null, draftState: 'правка публикации',
      loadTick: st.loadTick + 1,
    }));
  },

  stopAllEditing: () => set({ editingSched: null, editingPub: null, draftState: '' }),
}));
