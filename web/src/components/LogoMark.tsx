import { useId } from 'react';

/* Марка Magic Studio: лента, сложенная в M — грани от голубого к фиолетовому,
   тёмные фальцы на сгибах. Знак цветной, кладётся на нейтральный чип (.logo).
   id градиентов уникальны на экземпляр: ссылка на defs внутри display:none
   поддерева (например, скрытого сайдбара) молча не рендерится. */
export default function LogoMark({ size = 20 }: { size?: number }) {
  const id = useId();
  const g = (n: string) => `url(#${id}${n})`;
  return (
    <svg width={size} height={size} viewBox="0 0 36 36" aria-hidden="true">
      <defs>
        <linearGradient id={`${id}A`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#5AC8FA" /><stop offset="1" stopColor="#2AABEE" /></linearGradient>
        <linearGradient id={`${id}B`} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#1877C2" /><stop offset="1" stopColor="#3D4EC0" /></linearGradient>
        <linearGradient id={`${id}C`} x1="0" y1="0" x2="1" y2="0"><stop offset="0" stopColor="#6D79E8" /><stop offset="1" stopColor="#8B6BF0" /></linearGradient>
        <linearGradient id={`${id}D`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#9D7BFF" /><stop offset="1" stopColor="#6366F1" /></linearGradient>
      </defs>
      <polygon points="6,28 6,8 13,12 13,28" fill={g('A')} />
      <polygon points="6,8 13,12 18,21 18,28" fill={g('B')} />
      <polygon points="30,8 23,12 18,21 18,28" fill={g('C')} />
      <polygon points="23,28 23,12 30,8 30,28" fill={g('D')} />
      <polygon points="6,8 13,12 13,15.5" fill="#0E4B86" opacity=".55" />
      <polygon points="30,8 23,12 23,15.5" fill="#3B2F8F" opacity=".5" />
    </svg>
  );
}
