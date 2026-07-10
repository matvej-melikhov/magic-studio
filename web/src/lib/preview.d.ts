/* Типы для preview.js — сам модуль остаётся нетронутым JS (дословный порт) */
export declare const mathStore: Array<[string, boolean]>;
export declare function esc(s: string): string;
export declare function inline(text: string): string;
export declare function mediaBlock(url: string, caption?: string): string;
export declare function fmtDuration(sec: number): string;
export declare function attachMedia(root: HTMLElement): void;
export declare function buildContentHtml(src: string): string;
export declare function applyMath(root: HTMLElement): void;
