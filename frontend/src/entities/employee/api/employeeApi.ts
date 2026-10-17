import { baseApi } from '@/shared/api';
import { delay } from '@/shared/lib/time';

import { createMockEmployees } from './mockEmployees';
import {
  type Employee,
  type EmployeeRole,
  type EmployeesPage,
  type EmployeesQuery,
  type EmployeeStats,
} from '../model/types';

const PAGE_SIZE = 8;

let mockEmployees = createMockEmployees();

const updateEmployee = (id: string, patch: Partial<Employee>) => {
  mockEmployees = mockEmployees.map((employee) =>
    employee.id === id ? { ...employee, ...patch } : employee,
  );
};

export const employeeApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getEmployees: build.query<EmployeesPage, EmployeesQuery>({
      queryFn: async ({ search, role, status, page }) => {
        await delay(250);
        const query = search.trim().toLowerCase();
        const filtered = mockEmployees.filter(
          (employee) =>
            (role === 'all' || employee.role === role) &&
            (status === 'all' || employee.status === status) &&
            (!query ||
              [employee.name, employee.email, employee.department]
                .join(' ')
                .toLowerCase()
                .includes(query)),
        );
        const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
        const safePage = Math.min(Math.max(page, 1), pageCount);
        return {
          data: {
            items: filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE),
            found: filtered.length,
            total: mockEmployees.length,
            page: safePage,
            pageCount,
          },
        };
      },
      providesTags: ['Employee'],
    }),
    getEmployeeStats: build.query<EmployeeStats, undefined>({
      queryFn: async () => {
        await delay(200);
        return {
          data: {
            total: mockEmployees.length,
            active: mockEmployees.filter((employee) => employee.status === 'active').length,
            pending: mockEmployees.filter((employee) => employee.status === 'pending').length,
            aiDisabled: mockEmployees.filter((employee) => !employee.aiEnabled).length,
          },
        };
      },
      providesTags: ['Employee'],
    }),
    /** Отключение AI не влияет на работу обычной почты сотрудника. */
    setEmployeeAi: build.mutation<undefined, { id: string; enabled: boolean }>({
      queryFn: async ({ id, enabled }) => {
        await delay(300);
        updateEmployee(id, { aiEnabled: enabled });
        return { data: undefined };
      },
      invalidatesTags: ['Employee'],
    }),
    setEmployeeRole: build.mutation<undefined, { id: string; role: EmployeeRole }>({
      queryFn: async ({ id, role }) => {
        await delay(300);
        updateEmployee(id, { role });
        return { data: undefined };
      },
      invalidatesTags: ['Employee'],
    }),
  }),
});

export const {
  useGetEmployeesQuery,
  useGetEmployeeStatsQuery,
  useSetEmployeeAiMutation,
  useSetEmployeeRoleMutation,
} = employeeApi;
