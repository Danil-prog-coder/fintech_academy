import { X } from 'lucide-react';
import {
  type CSSProperties,
  useCallback,
  useEffect,
  useLayoutEffect,
  useReducer,
  useState,
  useSyncExternalStore,
} from 'react';

import { Button } from '@/shared/ui';

import styles from './OnboardingTour.module.css';
import { tourSteps } from '../../model/steps';
import {
  closeTour,
  isTourDone,
  isTourOpen,
  markTourDone,
  startTour,
  subscribeTour,
} from '../../model/tourStore';

interface OnboardingTourProps {
  /** Пользователь, для которого запоминаем «тур пройден»; null — ещё не загружен. */
  userId: number | null;
}

interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

const PAD = 6;
const CARD_WIDTH = 340;
const GAP = 14;

const findTarget = (target: string | undefined): HTMLElement | null =>
  target ? document.querySelector<HTMLElement>(`[data-tour="${target}"]`) : null;

const measure = (el: HTMLElement | null): Box | null => {
  if (!el) {
    return null;
  }
  const r = el.getBoundingClientRect();
  if (r.width === 0 && r.height === 0) {
    return null;
  }
  return {
    top: r.top - PAD,
    left: r.left - PAD,
    width: r.width + PAD * 2,
    height: r.height + PAD * 2,
  };
};

/** Карточка под подсветкой, а если снизу не помещается — над ней; не вылезает за края окна. */
const cardPosition = (box: Box | null): CSSProperties => {
  if (!box) {
    return {};
  }
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const width = Math.min(CARD_WIDTH, vw - 32);
  const left = Math.min(Math.max(16, box.left + box.width / 2 - width / 2), vw - width - 16);
  const below = box.top + box.height + GAP;
  return below + 220 < vh
    ? { top: below, left, width }
    : { bottom: Math.max(16, vh - box.top + GAP), left, width };
};

/**
 * Пошаговый тур по интерфейсу с подсветкой элементов (data-tour="…").
 * Сам открывается при первом входе пользователя; повторно — через startTour() из меню.
 * Шаги, чьих элементов нет на текущей странице, пропускаются.
 */
export const OnboardingTour = ({ userId }: OnboardingTourProps) => {
  const open = useSyncExternalStore(subscribeTour, isTourOpen);
  const [index, setIndex] = useState(0);
  // Положение подсветки читаем из DOM при отрисовке; ресайз и прокрутка просто перерисовывают.
  const [, relayout] = useReducer((n: number) => n + 1, 0);

  useEffect(() => {
    if (userId !== null && !isTourDone(userId)) {
      startTour();
    }
  }, [userId]);

  const steps = tourSteps.filter((step) => !step.target || findTarget(step.target));
  const step = steps[Math.min(index, steps.length - 1)];
  const last = index >= steps.length - 1;

  const finish = useCallback(() => {
    if (userId !== null) {
      markTourDone(userId);
    }
    setIndex(0);
    closeTour();
  }, [userId]);

  useLayoutEffect(() => {
    if (!open) {
      return undefined;
    }
    findTarget(step?.target)?.scrollIntoView({ block: 'nearest' });
    window.addEventListener('resize', relayout);
    window.addEventListener('scroll', relayout, true);
    return () => {
      window.removeEventListener('resize', relayout);
      window.removeEventListener('scroll', relayout, true);
    };
  }, [open, step]);

  useEffect(() => {
    if (!open) {
      return undefined;
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        finish();
      } else if (event.key === 'ArrowRight' && !last) {
        setIndex((i) => i + 1);
      } else if (event.key === 'ArrowLeft') {
        setIndex((i) => Math.max(0, i - 1));
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
    };
  }, [open, last, finish]);

  if (!open || !step) {
    return null;
  }

  const highlighted = measure(findTarget(step.target));

  return (
    <div className={styles.root}>
      {highlighted ? (
        <div
          className={styles.spotlight}
          style={{
            top: highlighted.top,
            left: highlighted.left,
            width: highlighted.width,
            height: highlighted.height,
          }}
        />
      ) : (
        <div className={styles.backdrop} />
      )}
      <div
        className={highlighted ? styles.card : `${styles.card} ${styles.centered}`}
        style={cardPosition(highlighted)}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
      >
        <button type="button" className={styles.close} aria-label="Закрыть тур" onClick={finish}>
          <X size={18} />
        </button>
        <p className={styles.counter}>
          Шаг {index + 1} из {steps.length}
        </p>
        <h2 id="tour-title" className={styles.title}>
          {step.title}
        </h2>
        <p className={styles.text}>{step.text}</p>
        <div className={styles.actions}>
          {index === 0 ? (
            <Button variant="ghost" onClick={finish}>
              Пропустить
            </Button>
          ) : (
            <Button
              variant="ghost"
              onClick={() => {
                setIndex(index - 1);
              }}
            >
              Назад
            </Button>
          )}
          <Button
            variant="primary"
            autoFocus
            onClick={() => {
              if (last) {
                finish();
              } else {
                setIndex(index + 1);
              }
            }}
          >
            {last ? 'Начать работу' : index === 0 ? 'Показать' : 'Дальше'}
          </Button>
        </div>
      </div>
    </div>
  );
};
