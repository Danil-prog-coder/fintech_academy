import { baseApi } from '@/shared/api';

export type TicketStatus = 'waiting' | 'in_progress' | 'waiting_customer' | 'resolved' | 'closed';

export interface TicketMessage {
  id: number;
  author: 'user' | 'support' | 'system';
  author_name: string | null;
  text: string;
  internal: boolean;
  created_at: string;
}

export interface Ticket {
  key: string;
  status: TicketStatus;
  priority: string;
  reason: string;
  summary: string;
  question: string;
  external_id: string;
  created_at: string;
  taken_at: string | null;
  closed_at: string | null;
  user_rating: number | null;
  jira_key: string | null;
  jira_state: string;
  jira_error: string | null;
  history: { role: string; text: string }[];
  messages?: TicketMessage[];
}

export const ticketApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getTickets: build.query<{ escalations: Ticket[] }, string>({
      query: (status) => `/escalations?status=${status}`,
      providesTags: ['Tickets'],
    }),
    getTicket: build.query<Ticket, string>({
      query: (key) => `/escalations/${key}`,
      providesTags: ['Ticket'],
    }),
    takeTicket: build.mutation<Ticket, string>({
      query: (key) => ({ url: `/escalations/${key}/take`, method: 'POST' }),
      invalidatesTags: ['Ticket', 'Tickets'],
    }),
    replyTicket: build.mutation<{ id: number }, { key: string; text: string; internal: boolean }>({
      query: ({ key, ...body }) => ({ url: `/escalations/${key}/reply`, method: 'POST', body }),
      invalidatesTags: ['Ticket', 'Tickets'],
    }),
    setTicketStatus: build.mutation<Ticket, { key: string; status: TicketStatus }>({
      query: ({ key, status }) => ({
        url: `/escalations/${key}/status`,
        method: 'POST',
        body: { status },
      }),
      invalidatesTags: ['Ticket', 'Tickets', 'Stats'],
    }),
    saveTicketToKb: build.mutation<
      { saved: boolean },
      { key: string; answer?: string; section?: string }
    >({
      query: ({ key, ...body }) => ({
        url: `/escalations/${key}/save-to-kb`,
        method: 'POST',
        body,
      }),
    }),
  }),
});

export const {
  useGetTicketsQuery,
  useGetTicketQuery,
  useTakeTicketMutation,
  useReplyTicketMutation,
  useSetTicketStatusMutation,
  useSaveTicketToKbMutation,
} = ticketApi;
