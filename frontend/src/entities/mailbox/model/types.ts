export type Security = 'ssl' | 'starttls' | 'none';

export type FolderRole = 'inbox' | 'sent' | 'drafts' | 'trash' | 'junk' | 'archive';

export interface AccountCreate {
  email: string;
  password: string;
  display_name?: string;
  username?: string;
  imap_host?: string;
  imap_port?: number;
  imap_security?: Security;
  smtp_host?: string;
  smtp_port?: number;
  smtp_security?: Security;
}

export interface MailAccount {
  id: number;
  email: string;
  display_name: string | null;
  imap_host: string;
  smtp_host: string;
  created_at: string;
}

export interface MailFolder {
  path: string;
  name: string;
  role: FolderRole | null;
  total: number;
  unseen: number;
}

export interface Address {
  name: string | null;
  email: string;
}

export interface MessageSummary {
  uid: number;
  subject: string;
  sender: Address | null;
  to: Address[];
  date: string | null;
  snippet: string | null;
  seen: boolean;
  flagged: boolean;
  answered: boolean;
  draft: boolean;
  has_attachments: boolean;
  size: number;
}

export interface MessageList {
  folder: string;
  total: number;
  items: MessageSummary[];
}

export interface Attachment {
  index: number;
  filename: string;
  content_type: string;
  size: number;
  inline: boolean;
  content_id: string | null;
}

export interface MailMessage {
  uid: number;
  folder: string;
  message_id: string | null;
  in_reply_to: string | null;
  references: string | null;
  subject: string;
  sender: Address | null;
  to: Address[];
  cc: Address[];
  date: string | null;
  seen: boolean;
  flagged: boolean;
  answered: boolean;
  text: string | null;
  html: string | null;
  remote_images_blocked: boolean;
  attachments: Attachment[];
}

export interface MessageRef {
  accountId: number;
  folder: string;
  uid: number;
}

export interface MessagePatch {
  seen?: boolean;
  flagged?: boolean;
  move_to?: string;
}

export interface OutgoingAttachment {
  filename: string;
  content_type: string;
  content_base64: string;
}

export interface SendRequest {
  to: string[];
  cc: string[];
  bcc: string[];
  subject: string;
  text: string | null;
  html?: string | null;
  attachments: OutgoingAttachment[];
  in_reply_to?: string | null;
  references?: string | null;
  answered?: { folder: string; uid: number } | null;
}

export interface SendResult {
  message_id: string;
  saved_to_sent: boolean;
}

export interface DraftResult {
  message_id: string;
  folder: string;
}

export interface ListMessagesArgs {
  accountId: number;
  folder: string;
  unread: boolean;
  query: string;
  limit: number;
  offset: number;
}
