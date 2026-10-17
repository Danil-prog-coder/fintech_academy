import { type FileType } from '@/shared/ui';

/**
 * Статус версии документа. AI различает «найден», «вероятно актуален» и «согласован»:
 * поздняя дата сама по себе не доказывает согласование.
 */
export type DocumentApproval = 'approved' | 'probably_actual' | 'not_found' | 'restricted';

export interface DocumentFile {
  id: string;
  /** Группа версий одного документа. */
  family: string;
  name: string;
  fileType: FileType;
  sizeLabel: string;
  source: string;
  updatedLabel: string;
  approval: DocumentApproval;
  approvalNote: string;
}

/** Снимок документа для прикрепления к черновику. */
export interface DocumentAttachment {
  documentId: string;
  name: string;
  fileType: FileType;
  sizeLabel: string;
  source: string;
  approval: DocumentApproval;
  approvalNote: string;
  blocked: boolean;
  blockReason: string | null;
}
