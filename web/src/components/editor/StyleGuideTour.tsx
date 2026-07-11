import { useEffect, useLayoutEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTour } from '../../store/tour';
import { GUIDE_STEPS } from './guideSteps';
import '../../styles/tour.css';

interface Rect { top: number; left: number; width: number; height: number }

/* Интерактивный гид: вуаль с «дыркой» (box-shadow 0 0 0 9999px) вокруг
   кнопки текущего шага + карточка с пояснением. Стрелки/Esc работают. */
export default function StyleGuideTour() {
  const { active, step, stop, next, prev } = useTour();
  const [rect, setRect] = useState<Rect | null>(null);

  /* Позиционирование: ждём кадр (панель могла только что раскрыться),
     подскролливаем кнопку и меряем. Пересчёт на resize. */
  useLayoutEffect(() => {
    if (!active) return;
    let raf = 0;
    const measure = () => {
      const el = document.querySelector(GUIDE_STEPS[step].sel);
      if (!el) { setRect(null); return; }
      el.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'instant' as ScrollBehavior });
      const r = el.getBoundingClientRect();
      setRect({ top: r.top, left: r.left, width: r.width, height: r.height });
    };
    raf = requestAnimationFrame(measure);
    window.addEventListener('resize', measure);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', measure);
    };
  }, [active, step]);

  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') stop();
      else if (e.key === 'ArrowRight' || e.key === 'Enter') next();
      else if (e.key === 'ArrowLeft') prev();
      else return;
      e.preventDefault();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [active, stop, next, prev]);

  if (!active || !rect) return null;

  const s = GUIDE_STEPS[step];
  const pad = 6;
  const ring = {
    top: rect.top - pad,
    left: rect.left - pad,
    width: rect.width + pad * 2,
    height: rect.height + pad * 2,
  };
  /* Карточка под кнопкой; если не влезает — над ней. Слева зажимаем в экран */
  const cardW = 320;
  const below = ring.top + ring.height + 14;
  const showAbove = below + 190 > window.innerHeight;
  const cardLeft = Math.max(10, Math.min(
    ring.left + ring.width / 2 - cardW / 2,
    window.innerWidth - cardW - 10));

  return createPortal(
    <>
      <div className="tour-block" onClick={stop} />
      <div className="tour-ring" style={ring} />
      <div className="tour-card" style={{
        left: cardLeft, width: cardW,
        ...(showAbove
          ? { bottom: window.innerHeight - ring.top + 14 }
          : { top: below }),
      }}>
        <div className="tour-card-head">
          <b>{s.title}</b>
          {s.key && <kbd>{s.key}</kbd>}
          <button className="tour-x" title="Закрыть (Esc)" onClick={stop}>✕</button>
        </div>
        {s.syntax && <code className="tour-syntax">{s.syntax}</code>}
        <p>{s.text}</p>
        <div className="tour-nav">
          <span className="tour-count">{step + 1} / {GUIDE_STEPS.length}</span>
          <button className="btn ghost" onClick={prev} disabled={step === 0}>Назад</button>
          <button className="btn primary" onClick={next}>
            {step + 1 === GUIDE_STEPS.length ? 'Готово' : 'Далее'}
          </button>
        </div>
      </div>
    </>,
    document.body,
  );
}
