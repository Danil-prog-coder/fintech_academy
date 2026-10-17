import { ArrowRight, ChevronRight, Info, RefreshCw } from 'lucide-react';

import { type FoundLetter } from '@/features/ai-search';
import { Avatar, Button } from '@/shared/ui';

import styles from './LetterResults.module.css';

interface LetterResultsProps {
  letters: FoundLetter[];
  unavailableSource: string | null;
  caveatAccepted: boolean;
  onOpen: (letter: FoundLetter) => void;
  onRetry: () => void;
  onAcceptCaveat: () => void;
}

/** Найденные письма; при недоступном источнике — явная оговорка о неполном поиске. */
export const LetterResults = ({
  letters,
  unavailableSource,
  caveatAccepted,
  onOpen,
  onRetry,
  onAcceptCaveat,
}: LetterResultsProps) => (
  <div className={styles.results}>
    <p className={styles.heading}>Результаты ({letters.length})</p>
    <ul className={styles.list}>
      {letters.map((letter) => (
        <li key={letter.id}>
          <button
            type="button"
            className={styles.letter}
            onClick={() => {
              onOpen(letter);
            }}
          >
            <Avatar initials={letter.initials} size="md" />
            <span className={styles.body}>
              <span className={styles.top}>
                <span className={styles.subject}>{letter.subject}</span>
                <span className={styles.date}>{letter.dateLabel}</span>
              </span>
              <span className={styles.from}>{letter.from}</span>
              <span className={styles.snippet}>{letter.snippet}</span>
            </span>
            <ChevronRight size={18} className={styles.chevron} />
          </button>
        </li>
      ))}
    </ul>

    {unavailableSource && !caveatAccepted ? (
      <>
        <div className={styles.info}>
          <Info size={22} className={styles.infoIcon} />
          <div>
            <p className={styles.infoTitle}>Один источник временно недоступен</p>
            <p className={styles.infoText}>
              Не удалось выполнить поиск в источнике «{unavailableSource}». Попробуйте повторить
              поиск позже или продолжить с учётом доступных результатов.
            </p>
          </div>
        </div>
        <Button
          variant="primary"
          size="lg"
          fullWidth
          icon={<RefreshCw size={18} />}
          onClick={onRetry}
        >
          Повторить поиск
        </Button>
        <Button size="lg" fullWidth icon={<ArrowRight size={18} />} onClick={onAcceptCaveat}>
          Продолжить с оговоркой
        </Button>
      </>
    ) : null}

    {unavailableSource && caveatAccepted ? (
      <p className={styles.caveat}>
        Результаты неполные: источник «{unavailableSource}» был недоступен во время поиска.
      </p>
    ) : null}
  </div>
);
