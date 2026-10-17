import { type DocumentAttachment, type DocumentFile } from '../model/types';

interface AttachmentContext {
  /** Среди получателей есть внешний адресат. */
  externalRecipient: boolean;
}

/**
 * Готовит вложение для черновика. Корпоративный запрет передачи
 * блокирует вложение, а не просто показывает предупреждение.
 */
export const toAttachment = (
  document: DocumentFile,
  { externalRecipient }: AttachmentContext,
): DocumentAttachment => {
  const blocked = externalRecipient && document.approval === 'restricted';

  return {
    documentId: document.id,
    name: document.name,
    fileType: document.fileType,
    sizeLabel: document.sizeLabel,
    source: document.source,
    approval: document.approval,
    approvalNote: document.approvalNote,
    blocked,
    blockReason: blocked ? 'Передача внешнему получателю запрещена политикой компании.' : null,
  };
};
