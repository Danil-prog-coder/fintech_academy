import { type AttachmentInfo, type DraftAttachment } from '@/entities/qa';

import { fileToBase64 } from './files';

/** Совпадает с лимитом сервера MAIL_ASK_ATTACHMENT_BYTES. */
export const AI_MAX_FILE_BYTES = 10 * 1024 * 1024;
export const AI_MAX_FILES = 10;

/** Форматы, из которых сервер извлекает текст: текст и код, PDF, DOCX. */
const AI_READABLE_EXTENSIONS = new Set(
  (
    'txt text md markdown rst adoc csv tsv json jsonl yaml yml toml ini cfg conf properties xml ' +
    'html htm log sql py js mjs ts tsx jsx java kt go rs c h cpp hpp cs rb php sh ps1 bat swift ' +
    'scala css scss vue graphql proto tf gradle pdf docx'
  ).split(' '),
);

const extension = (name: string) => {
  const dot = name.lastIndexOf('.');
  return dot === -1 ? '' : name.slice(dot + 1).toLowerCase();
};

export type AiSupport = 'ok' | 'unsupported' | 'too_large';

export const aiSupport = (file: File): AiSupport => {
  if (!AI_READABLE_EXTENSIONS.has(extension(file.name))) {
    return 'unsupported';
  }
  return file.size > AI_MAX_FILE_BYTES ? 'too_large' : 'ok';
};

export const aiSupportLabel: Record<AiSupport, string> = {
  ok: 'ИИ прочитает',
  unsupported: 'ИИ не читает этот формат',
  too_large: 'Слишком большой для ИИ',
};

/**
 * Файлы, которые уйдут на анализ, и отчёт о пропущенных ещё на клиенте
 * (чтобы не гонять на сервер картинки и архивы).
 */
export const prepareAiAttachments = async (
  files: File[],
): Promise<{ attachments: DraftAttachment[]; skipped: AttachmentInfo[] }> => {
  const readable: File[] = [];
  const skipped: AttachmentInfo[] = [];
  for (const file of files) {
    const support = aiSupport(file);
    if (support === 'ok' && readable.length < AI_MAX_FILES) {
      readable.push(file);
    } else {
      skipped.push({
        filename: file.name,
        status: support === 'ok' ? 'too_large' : support,
        chars: 0,
        truncated: false,
        message: support === 'ok' ? `ИИ читает не больше ${String(AI_MAX_FILES)} файлов.` : null,
      });
    }
  }
  const attachments = await Promise.all(
    readable.map(async (file) => ({
      filename: file.name,
      content_type: file.type || undefined,
      content_base64: await fileToBase64(file),
    })),
  );
  return { attachments, skipped };
};
