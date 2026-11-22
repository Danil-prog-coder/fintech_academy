import { appPasswordGuides, type MailProvider } from '../config/appPasswordGuides';

/** Определяет почтовый сервис по домену адреса; для незнакомого домена — null. */
export const detectMailProvider = (email: string): MailProvider | null => {
  const at = email.lastIndexOf('@');
  if (at === -1) return null;
  const domain = email
    .slice(at + 1)
    .trim()
    .toLowerCase();
  return appPasswordGuides.find((guide) => guide.domains.includes(domain))?.provider ?? null;
};
