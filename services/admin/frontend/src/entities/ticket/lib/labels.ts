import { type TicketStatus } from '../api/ticketApi';

export const ticketStatusLabel: Record<TicketStatus, string> = {
  waiting: 'Ждёт специалиста',
  in_progress: 'В работе',
  waiting_customer: 'Ждёт ответа пользователя',
  resolved: 'Решено',
  closed: 'Закрыто',
};
