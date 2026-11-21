import { refreshSession } from '@/shared/api';
import { env } from '@/shared/config';
import { getAccessToken } from '@/shared/lib/tokens';

import { type Attachment, type MessageRef } from '../model/types';

const request = (ref: MessageRef, attachment: Attachment) => {
  const { accountId, uid, folder } = ref;
  const url =
    `${env.apiUrl}/mail/accounts/${String(accountId)}/messages/${String(uid)}` +
    `/attachments/${String(attachment.index)}?folder=${encodeURIComponent(folder)}`;
  return fetch(url, { headers: { authorization: `Bearer ${getAccessToken() ?? ''}` } });
};

/** Скачивает вложение с авторизацией и отдаёт его браузеру как файл. */
export const downloadAttachment = async (ref: MessageRef, attachment: Attachment) => {
  let response = await request(ref, attachment);
  if (response.status === 401 && (await refreshSession())) {
    response = await request(ref, attachment);
  }
  if (!response.ok) {
    throw new Error('Не удалось скачать вложение.');
  }
  const blobUrl = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = blobUrl;
  link.download = attachment.filename;
  link.click();
  URL.revokeObjectURL(blobUrl);
};
