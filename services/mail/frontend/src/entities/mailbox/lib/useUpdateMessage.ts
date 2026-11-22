import { useAppDispatch } from '@/shared/lib/store';

import { mailboxApi, useUpdateMessageMutation } from '../api/mailboxApi';
import { type MessagePatch, type MessageRef } from '../model/types';

/** Меняет флаги/папку письма и сразу отражает флаги в открытом письме без повторного чтения. */
export const useUpdateMessage = () => {
  const dispatch = useAppDispatch();
  const [trigger, state] = useUpdateMessageMutation();

  const update = async (ref: MessageRef, patch: MessagePatch) => {
    await trigger({ ...ref, patch }).unwrap();
    dispatch(
      mailboxApi.util.updateQueryData('getMessage', ref, (draft) => {
        if (patch.seen !== undefined) {
          draft.seen = patch.seen;
        }
        if (patch.flagged !== undefined) {
          draft.flagged = patch.flagged;
        }
      }),
    );
  };

  return [update, state] as const;
};
