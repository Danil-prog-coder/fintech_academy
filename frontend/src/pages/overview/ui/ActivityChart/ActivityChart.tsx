import { type ActivityPoint } from '@/entities/organization';

import styles from './ActivityChart.module.css';

const WIDTH = 600;
const HEIGHT = 220;
const PADDING = { top: 16, right: 12, bottom: 28, left: 36 };
const MAX = 80;
const TICKS = [0, 20, 40, 60, 80];

const x = (index: number, count: number) =>
  PADDING.left + (index / Math.max(count - 1, 1)) * (WIDTH - PADDING.left - PADDING.right);

const y = (value: number) =>
  PADDING.top + (1 - value / MAX) * (HEIGHT - PADDING.top - PADDING.bottom);

/** Сглаженная линия через точки (кривые Безье по средним точкам). */
const smoothPath = (values: number[]) =>
  values.reduce((path, value, index) => {
    const px = x(index, values.length);
    const py = y(value);
    if (index === 0) {
      return `M ${String(px)} ${String(py)}`;
    }
    const prevX = x(index - 1, values.length);
    const prevY = y(values[index - 1] ?? value);
    const midX = (prevX + px) / 2;
    return `${path} C ${String(midX)} ${String(prevY)}, ${String(midX)} ${String(py)}, ${String(px)} ${String(py)}`;
  }, '');

interface ActivityChartProps {
  points: ActivityPoint[];
}

export const ActivityChart = ({ points }: ActivityChartProps) => {
  const drafts = smoothPath(points.map((point) => point.drafts));
  const searches = smoothPath(points.map((point) => point.searches));
  const baseline = y(0);
  const lastX = x(points.length - 1, points.length);

  return (
    <figure className={styles.figure}>
      <div className={styles.legend}>
        <span className={styles.legendItem}>
          <span className={styles.dotDrafts} />
          AI-черновики
        </span>
        <span className={styles.legendItem}>
          <span className={styles.dotSearches} />
          AI-поиски
        </span>
      </div>
      <svg
        className={styles.chart}
        viewBox={`0 0 ${String(WIDTH)} ${String(HEIGHT)}`}
        role="img"
        aria-label="Активность сотрудников за 30 дней: AI-черновики и AI-поиски"
      >
        <defs>
          <linearGradient id="draftsFill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" className={styles.fillStart} />
            <stop offset="100%" className={styles.fillEnd} />
          </linearGradient>
        </defs>
        {TICKS.map((tick) => (
          <g key={tick}>
            <line
              className={styles.grid}
              x1={PADDING.left}
              x2={WIDTH - PADDING.right}
              y1={y(tick)}
              y2={y(tick)}
            />
            <text className={styles.axis} x={PADDING.left - 8} y={y(tick) + 4} textAnchor="end">
              {tick}
            </text>
          </g>
        ))}
        <path
          d={`${drafts} L ${String(lastX)} ${String(baseline)} L ${String(PADDING.left)} ${String(baseline)} Z`}
          fill="url(#draftsFill)"
        />
        <path d={searches} className={styles.searches} />
        <path d={drafts} className={styles.drafts} />
        {points.map((point, index) =>
          index % 5 === 0 || index === points.length - 1 ? (
            <text
              key={point.label}
              className={styles.axis}
              x={x(index, points.length)}
              y={HEIGHT - 6}
              textAnchor="middle"
            >
              {point.label}
            </text>
          ) : null,
        )}
      </svg>
    </figure>
  );
};
