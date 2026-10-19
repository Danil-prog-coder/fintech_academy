export interface Organization {
  name: string;
  description: string;
  inn: string;
  industry: string;
  employees: number;
  connectedAt: string;
  plan: string;
  active: boolean;
}

export interface AdminRoleAssignment {
  id: string;
  name: string;
  initials: string;
  email: string;
  role: 'admin' | 'security';
  active: boolean;
  assignedAt: string;
}

export interface OrgSetting {
  id: 'notifications' | 'securityPolicy' | 'invites' | 'auditRetention';
  title: string;
  description: string;
  value: string;
  toggle: boolean | null;
}

export interface ActivityPoint {
  label: string;
  drafts: number;
  searches: number;
}

export interface OverviewStats {
  employees: number;
  active: number;
  drafts: number;
  searches: number;
  trends: { employees: string; active: string; drafts: string; searches: string };
  activity: ActivityPoint[];
}

export type PolicyId = 'transfer' | 'retention' | 'features' | 'attachments' | 'links';

export interface SecurityPolicy {
  id: PolicyId;
  title: string;
  description: string;
  value: string;
  options: string[];
  enabled: boolean;
}
