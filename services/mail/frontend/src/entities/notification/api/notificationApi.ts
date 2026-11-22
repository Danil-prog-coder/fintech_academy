import { baseApi } from '@/shared/api';

export interface Notification {
  id: number;
  type: string;
  project_id: string;
  title: string;
  text: string;
  read: boolean;
  created_at: string;
}

export const notificationApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    getNotifications: build.query<{ notifications: Notification[] }, undefined>({
      query: () => '/notifications',
      providesTags: ['Notifications'],
    }),
    markRead: build.mutation<undefined, { ids?: number[] }>({
      query: (body) => ({ url: '/notifications/read', method: 'POST', body }),
      invalidatesTags: ['Notifications'],
    }),
  }),
});

export const { useGetNotificationsQuery, useMarkReadMutation } = notificationApi;
