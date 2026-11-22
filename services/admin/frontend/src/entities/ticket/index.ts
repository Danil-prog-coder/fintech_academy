export {
  useGetTicketQuery,
  useGetTicketsQuery,
  useReplyTicketMutation,
  useSaveTicketToKbMutation,
  useSetTicketStatusMutation,
  useTakeTicketMutation,
  type Ticket,
  type TicketMessage,
  type TicketStatus,
} from './api/ticketApi';
export { ticketStatusLabel } from './lib/labels';
