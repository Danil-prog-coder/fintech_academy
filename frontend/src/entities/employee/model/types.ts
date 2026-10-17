export type EmployeeRole = 'employee' | 'admin' | 'security';

export type EmployeeStatus = 'active' | 'pending' | 'disabled';

export interface Employee {
  id: string;
  name: string;
  initials: string;
  email: string;
  department: string;
  role: EmployeeRole;
  status: EmployeeStatus;
  aiEnabled: boolean;
}

export interface EmployeesQuery {
  search: string;
  role: EmployeeRole | 'all';
  status: EmployeeStatus | 'all';
  page: number;
}

export interface EmployeesPage {
  items: Employee[];
  found: number;
  total: number;
  page: number;
  pageCount: number;
}

export interface EmployeeStats {
  total: number;
  active: number;
  pending: number;
  aiDisabled: number;
}

export const roleLabels: Record<EmployeeRole, string> = {
  employee: 'Сотрудник',
  admin: 'Администратор',
  security: 'Специалист ИБ',
};

export const statusLabels: Record<EmployeeStatus, string> = {
  active: 'Активен',
  pending: 'Ожидание',
  disabled: 'Отключён',
};
