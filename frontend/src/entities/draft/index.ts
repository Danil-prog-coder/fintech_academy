export {
  draftAttachmentRemoved,
  draftAttachmentSet,
  draftDiscarded,
  draftEnsured,
  draftRecipientRemoved,
  draftSaved,
  draftSlice,
  draftsReset,
  draftTextChanged,
  selectDraft,
  selectDrafts,
} from './model/draftSlice';
export type { Draft, DraftAttachment, DraftSaveState, Recipient } from './model/types';
