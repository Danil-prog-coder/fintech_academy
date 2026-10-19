import styles from './Skeleton.module.css';

interface SkeletonProps {
  width?: string;
  height?: number;
}

export const Skeleton = ({ width = '100%', height = 12 }: SkeletonProps) => (
  // Размеры динамические, поэтому задаются inline.
  <span className={styles.skeleton} style={{ width, height }} aria-hidden="true" />
);
