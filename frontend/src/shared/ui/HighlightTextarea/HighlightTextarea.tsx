import { Fragment, type Ref } from 'react';

import styles from './HighlightTextarea.module.css';

interface Segment {
  text: string;
  marked: boolean;
}

/** Делит текст на фрагменты, помечая вхождения подсвечиваемых строк. */
const splitByHighlights = (value: string, highlights: readonly string[]): Segment[] => {
  const needles = highlights.filter(Boolean);
  const segments: Segment[] = [];
  let rest = value;

  while (rest.length > 0) {
    let bestIndex = -1;
    let bestNeedle = '';
    for (const needle of needles) {
      const index = rest.indexOf(needle);
      if (index !== -1 && (bestIndex === -1 || index < bestIndex)) {
        bestIndex = index;
        bestNeedle = needle;
      }
    }
    if (bestIndex === -1) {
      segments.push({ text: rest, marked: false });
      break;
    }
    if (bestIndex > 0) {
      segments.push({ text: rest.slice(0, bestIndex), marked: false });
    }
    segments.push({ text: bestNeedle, marked: true });
    rest = rest.slice(bestIndex + bestNeedle.length);
  }

  return segments;
};

interface HighlightTextareaProps {
  value: string;
  onChange: (value: string) => void;
  label: string;
  placeholder?: string;
  highlights?: readonly string[];
  disabled?: boolean;
  ref?: Ref<HTMLTextAreaElement>;
}

/**
 * Обычное редактируемое поле, поверх которого подсвечиваются фрагменты текста.
 * Подложка повторяет текст и задаёт высоту — поле растёт вместе с содержимым.
 */
export const HighlightTextarea = ({
  value,
  onChange,
  label,
  placeholder,
  highlights = [],
  disabled = false,
  ref,
}: HighlightTextareaProps) => (
  <div className={styles.wrapper}>
    <div className={styles.backdrop} aria-hidden="true">
      {splitByHighlights(value, highlights).map((segment, index) => (
        // Порядок сегментов стабилен для заданного текста.
        // eslint-disable-next-line react-x/no-array-index-key -- сегменты не имеют собственных id
        <Fragment key={index}>
          {segment.marked ? <mark className={styles.mark}>{segment.text}</mark> : segment.text}
        </Fragment>
      ))}
      {'\n'}
    </div>
    <textarea
      ref={ref}
      className={styles.textarea}
      aria-label={label}
      value={value}
      placeholder={placeholder}
      disabled={disabled}
      spellCheck
      onChange={(event) => {
        onChange(event.target.value);
      }}
    />
  </div>
);
