import { create } from 'zustand';
import { api } from '../api/client';

export interface Channel { username: string; title: string }
export interface Draft { id: string; title: string; markdown: string; updated: number }
export interface SchedPost {
  id: string; target: string; markdown: string; when: number;
  status: 'pending' | 'sending' | 'error'; error?: string;
}
export interface PubPost {
  id: string; target: string; title: string; markdown: string;
  when: number; message_id?: number;
}

interface AppState {
  name: string;
  channels: Channel[];
  drafts: Draft[];
  scheduled: SchedPost[];
  published: PubPost[];
  refresh: () => Promise<void>;
}

export const useAppState = create<AppState>((set) => ({
  name: '',
  channels: [],
  drafts: [],
  scheduled: [],
  published: [],

  refresh: async () => {
    const resp = await api('/api/state');
    if (!resp.ok) return;
    set({
      name: (resp.name as string) || '',
      channels: (resp.channels as Channel[]) || [],
      drafts: (resp.drafts as Draft[]) || [],
      scheduled: (resp.scheduled as SchedPost[]) || [],
      published: (resp.published as PubPost[]) || [],
    });
  },
}));
