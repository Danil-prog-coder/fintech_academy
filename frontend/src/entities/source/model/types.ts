export type SourceKind = 'mail' | 'documents' | 'other';

export type SourceStatus = 'working' | 'attention' | 'no_access';

export interface Source {
  id: string;
  name: string;
  kind: SourceKind;
  typeLabel: string;
  allowedData: string;
  status: SourceStatus;
  lastCheckLabel: string;
  lastCheckResult: string;
  /** Использование за 30 дней (агрегированно, без содержания писем). */
  aiActions: number;
}
