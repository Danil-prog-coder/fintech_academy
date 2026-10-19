import { Search, SendHorizontal } from 'lucide-react';
import { type Ref, useState } from 'react';

import { IconButton, TextField } from '@/shared/ui';

import styles from './SearchForm.module.css';

interface SearchFormProps {
  initialQuery: string;
  placeholder: string;
  label: string;
  variant: 'main' | 'refine';
  onSubmit: (query: string) => void;
  inputRef?: Ref<HTMLInputElement>;
}

/** Свободная формулировка вопроса; тип файла указывать не нужно. */
export const SearchForm = ({
  initialQuery,
  placeholder,
  label,
  variant,
  onSubmit,
  inputRef,
}: SearchFormProps) => {
  const [query, setQuery] = useState(initialQuery);

  return (
    <form
      className={styles.form}
      onSubmit={(event) => {
        event.preventDefault();
        if (query.trim()) {
          onSubmit(query.trim());
        }
      }}
    >
      <TextField
        ref={inputRef}
        label={label}
        placeholder={placeholder}
        value={query}
        onChange={setQuery}
        size="lg"
        highlighted={variant === 'main'}
        icon={variant === 'main' ? <Search size={22} /> : undefined}
        clearable={variant === 'main'}
        trailing={
          variant === 'refine' ? (
            <IconButton
              type="submit"
              label="Уточнить"
              icon={<SendHorizontal size={20} />}
              disabled={!query.trim()}
            />
          ) : undefined
        }
      />
    </form>
  );
};
