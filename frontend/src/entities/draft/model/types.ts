import { type FileType } from '@/shared/ui';

export interface Recipient {
  name: string;
  email: string;
  external: boolean;
}

/** Вложение черновика (структурно совпадает со снимком документа). */
export interface DraftAttachment {
  documentId: string;
  name: string;
  fileType: FileType;
  sizeLabel: string;
  source: string;
  approval: 'approved' | 'probably_actual' | 'not_found' | 'restricted';
  approvalNote: string;
  blocked: boolean;
  blockReason: string | null;
}

export type DraftSaveState = 'idle' | 'saving' | 'saved';

/** Черновик ответа хранится почтовым клиентом; AI только помогает его заполнить. */
export interface Draft {
  letterId: string;
  to: Recipient[];
  text: string;
  attachment: DraftAttachment | null;
  saveState: DraftSaveState;
  savedAt: string | null;
}
