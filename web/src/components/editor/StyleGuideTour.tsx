import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTour } from '../../store/tour';
import { GUIDE_STEPS } from './guideSteps';
import { mathStore, buildContentHtml, applyMath } from '../../lib/preview';
import '../../styles/tour.css';

/* Живой пример в карточке: markdown шага рендерится тем же движком,
   что и предпросмотр — в мини-пузыре поста. Демонстрируемый фрагмент
   обводится пунктиром (.tour-hit по селектору hit шага). */
function StepDemo({ demo, hit, hitBare, autoplay }: {
  demo: string; hit?: string; hitBare?: boolean; autoplay?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    mathStore.length = 0;
    el.innerHTML = `<div class="bubble"><div class="content">${buildContentHtml(demo)}</div></div>`;
    applyMath(el);
    if (hit) el.querySelectorAll(hit).forEach((n) =>
      n.classList.add(hitBare ? 'tour-hit-bare' : 'tour-hit'));
    /* Слайдшоу в примере листается само — видно, как оно работает */
    if (autoplay) {
      const ss = el.querySelector<HTMLElement>('.slideshow');
      if (ss) {
        const n = ss.querySelectorAll('img').length;
        let idx = 0;
        const timer = setInterval(() => {
          idx = (idx + 1) % n;
          ss.scrollTo({ left: idx * ss.clientWidth, behavior: 'smooth' });
        }, 1800);
        return () => clearInterval(timer);
      }
    }
  }, [demo, hit, hitBare, autoplay]);
  return <div className={'tour-demo' + (hit ? ' has-hit' : '')} ref={ref} />;
}

interface Rect { top: number; left: number; width: number; height: number }

/* Интерактивный гид: вуаль с «дыркой» (box-shadow 0 0 0 9999px) вокруг
   кнопки текущего шага + карточка с пояснением. Стрелки/Esc работают. */
export default function StyleGuideTour() {
  const { active, step, stop, next, prev } = useTour();
  const [rect, setRect] = useState<Rect | null>(null);
  const [cardTop, setCardTop] = useState(0);

  /* Позиционирование: ждём кадр (панель могла только что раскрыться),
     подскролливаем кнопку и меряем. Пересчёт на resize.
     Карточка НЕ следует за кольцом: стоит на одном месте под панелью,
     чтобы «Далее» не двигалась и её можно было щёлкать не целясь. */
  useLayoutEffect(() => {
    if (!active) return;
    let raf = 0;
    const measure = () => {
      const el = document.querySelector(GUIDE_STEPS[step].sel);
      if (!el) { setRect(null); return; }
      el.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'instant' as ScrollBehavior });
      const r = el.getBoundingClientRect();
      setRect({ top: r.top, left: r.left, width: r.width, height: r.height });
      const toolbar = document.querySelector('.toolbar');
      if (toolbar) setCardTop(toolbar.getBoundingClientRect().bottom + 20);
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
  return createPortal(
    <>
      <div className="tour-block" onClick={stop} />
      <div className="tour-ring" style={ring} />
      <div className="tour-card" style={{ top: cardTop }}>
        <div className="tour-card-head">
          <b>{s.title}</b>
          {s.key && <kbd>{s.key}</kbd>}
          <button className="tour-x" title="Закрыть (Esc)" onClick={stop}>✕</button>
        </div>
        <div className="tour-body">
          {s.demo && <StepDemo demo={s.demo} hit={s.hit} hitBare={s.hitBare} autoplay={s.autoplay} />}
          <p>{s.text}</p>
        </div>
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
