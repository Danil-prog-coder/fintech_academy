export type RepoStatus =
  'not_connected' | 'indexing' | 'ready' | 'updating' | 'error' | 'reauth_required';

export interface RepoStatusInfo {
  status: RepoStatus;
  url: string | null;
  owner: string | null;
  name: string | null;
  last_commit: string | null;
  webhook_registered: boolean;
  webhook_hint: string | null;
  last_error: string | null;
  indexed_files: number;
  skipped_files: number;
  connected_at: string | null;
}

export interface RepoConnectRequest {
  url: string;
  github_token?: string;
  replace?: boolean;
}

/** Пока индекс строится или обновляется, статус нужно опрашивать. */
export const isRepoBusy = (status: RepoStatus | undefined): boolean =>
  status === 'indexing' || status === 'updating';
