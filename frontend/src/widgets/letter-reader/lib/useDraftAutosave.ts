import { useEffect } from 'react';

import { draftSaved, type Draft } from '@/entities/draft';
import { useAppDispatch } from '@/shared/lib/store';
import { formatTime } from '@/shared/lib/time';

const AUTOSAVE_DELAY_MS = 900;

/** Имитация автосохранения черновика почтовым клиентом. */
export const useDraftAutosave = (draft: Draft | undefined) => {
  const dispatch = useAppDispatch();
  const letterId = draft?.letterId;
  const saveState = draft?.saveState;
  const text = draft?.text;

  useEffect(() => {
    if (!letterId || saveState !== 'saving') {
      return undefined;
    }
    const timer = setTimeout(() => {
      dispatch(draftSaved({ letterId, time: formatTime() }));
    }, AUTOSAVE_DELAY_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [dispatch, letterId, saveState, text]);
};
