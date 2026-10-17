import styles from './HomePage.module.css';

export const HomePage = () => (
  <main className={styles.page}>
    <h1 className={styles.title}>Fintech Academy</h1>
    <p className={styles.subtitle}>
      Frontend initialized: React + TypeScript + Redux Toolkit, FSD.
    </p>
  </main>
);
