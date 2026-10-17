import { ArrowUpRight } from 'lucide-react';
import { type ReactNode } from 'react';

import styles from './StatCard.module.css';

interface StatCardProps {
  icon: ReactNode;
  value: string;
  label: string;
  trend?: string;
  trendNote?: string;
}

export const StatCard = ({ icon, value, label, trend, trendNote }: StatCardProps) => (
  <article className={styles.card}>
    <span className={styles.icon}>{icon}</span>
    <div className={styles.body}>
      <p className={styles.value}>{value}</p>
      <p className={styles.label}>{label}</p>
      {trend ? (
        <p className={styles.trend}>
          <span className={styles.trendValue}>
            <ArrowUpRight size={16} strokeWidth={2.5} />
            {trend}
          </span>
          {trendNote ? <span className={styles.trendNote}>{trendNote}</span> : null}
        </p>
      ) : null}
    </div>
  </article>
);
