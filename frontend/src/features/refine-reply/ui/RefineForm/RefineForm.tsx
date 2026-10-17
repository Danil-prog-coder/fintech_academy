import { ChevronRight, Search } from 'lucide-react';
import { type Ref, useState } from 'react';

import { useAppDispatch, useAppSelector } from '@/shared/lib/store';
import { IconButton, Spinner, TextField } from '@/shared/ui';

import styles from './RefineForm.module.css';
import { refineReply } from '../../model/refineReply';
import { selectRefine } from '../../model/refineSlice';

interface RefineFormProps {
  letterId: string;
  initialQuery?: string;
  inputRef?: Ref<HTMLInputElement>;
}

export const RefineForm = ({ letterId, initialQuery = '', inputRef }: RefineFormProps) => {
  const dispatch = useAppDispatch();
  const { status } = useAppSelector((state) => selectRefine(state, letterId));
  const [query, setQuery] = useState(initialQuery);
  const loading = status === 'loading';

  return (
    <form
      className={styles.form}
      onSubmit={(event) => {
        event.preventDefault();
        void dispatch(refineReply({ letterId, query }));
      }}
    >
      <TextField
        ref={inputRef}
        label="Что изменить в ответе?"
        placeholder="Что изменить в ответе?"
        value={query}
        onChange={setQuery}
        icon={<Search size={18} />}
        disabled={loading}
        trailing={
          loading ? (
            <Spinner size="sm" label="Изменяем ответ" />
          ) : (
            <IconButton
              type="submit"
              size="sm"
              variant="outline"
              label="Применить"
              icon={<ChevronRight size={16} />}
              disabled={!query.trim()}
            />
          )
        }
      />
      <p className={styles.hint}>
        AI учитывает контекст письма.
        <br />
        Ваши правки сохраняются.
      </p>
    </form>
  );
};
