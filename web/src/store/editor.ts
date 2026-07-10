import { create } from 'zustand';
import { lsStore } from '../lib/lsStore';
import type { SchedPost, PubPost } from './appState';

/* Кросс-разделные флаги редактора: текущий черновик, режимы правки
   отложенного/опубликованного. Сам текст живёт в неконтролируемом
   textarea (см. фазу 2) и зеркалится в localStorage, а не в стор. */
interface EditorState {
  currentDraftId: string | null;
  editingSched: SchedPost | null;
  editingPub: PubPost | null;
  draftState: string;               // подпись у заголовка «Разметка»
  setDraftState: (s: string) => void;
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

  setDraftState: (s) => set({ draftState: s }),

  loadDraft: (id, markdown) => {
    lsStore.set('draft', markdown);
    lsStore.set('draftId', id);
    set({ currentDraftId: id, draftState: 'черновик загружен' });
  },

  newPost: () => {
    lsStore.set('draft', '');
    lsStore.del('draftId');
    set({ currentDraftId: null, draftState: '', editingSched: null, editingPub: null });
  },

  startEditingSched: (post) => {
    lsStore.set('draft', post.markdown);
    set({ editingSched: post, editingPub: null, draftState: 'правка отложенного' });
  },

  startEditingPub: (post) => {
    lsStore.set('draft', post.markdown);
    set({ editingPub: post, editingSched: null, draftState: 'правка публикации' });
  },

  stopAllEditing: () => set({ editingSched: null, editingPub: null, draftState: '' }),
}));
