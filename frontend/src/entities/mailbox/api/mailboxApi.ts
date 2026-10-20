import { baseApi } from '@/shared/api';

import {
  type AccountCreate,
  type DraftResult,
  type ListMessagesArgs,
  type MailAccount,
  type MailFolder,
  type MailMessage,
  type MessageList,
  type MessagePatch,
  type MessageRef,
  type SendRequest,
  type SendResult,
} from '../model/types';

const messageUrl = ({ accountId, uid }: MessageRef) =>
  `/mail/accounts/${String(accountId)}/messages/${String(uid)}`;

export const mailboxApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    listAccounts: build.query<MailAccount[], undefined>({
      query: () => '/mail/accounts',
      providesTags: ['Account'],
    }),
    connectAccount: build.mutation<MailAccount, AccountCreate>({
      query: (body) => ({ url: '/mail/accounts', method: 'POST', body }),
      invalidatesTags: ['Account'],
    }),
    disconnectAccount: build.mutation<undefined, number>({
      query: (id) => ({ url: `/mail/accounts/${String(id)}`, method: 'DELETE' }),
      invalidatesTags: ['Account', 'Folders', 'Messages', 'Message'],
    }),
    listFolders: build.query<MailFolder[], number>({
      query: (accountId) => `/mail/accounts/${String(accountId)}/folders`,
      providesTags: ['Folders'],
    }),
    listMessages: build.query<MessageList, ListMessagesArgs>({
      query: ({ accountId, folder, unread, query, limit, offset }) => {
        const base = `/mail/accounts/${String(accountId)}/messages`;
        // Поисковая фраза идёт в теле POST, чтобы не попадать в URL и журналы.
        if (query) {
          return {
            url: `${base}/search`,
            method: 'POST',
            body: { q: query, folder, unread, limit, offset },
          };
        }
        return { url: base, params: { folder, unread, limit, offset } };
      },
      providesTags: ['Messages'],
    }),
    getMessage: build.query<MailMessage, MessageRef>({
      query: (ref) => ({ url: messageUrl(ref), params: { folder: ref.folder } }),
      providesTags: ['Message'],
      // Чтение помечает письмо прочитанным на сервере: обновляем список и счётчики.
      onQueryStarted: async (_ref, { dispatch, queryFulfilled }) => {
        try {
          await queryFulfilled;
          dispatch(baseApi.util.invalidateTags(['Messages', 'Folders']));
        } catch {
          // Ошибку покажет сам экран письма.
        }
      },
    }),
    updateMessage: build.mutation<undefined, MessageRef & { patch: MessagePatch }>({
      query: (ref) => ({
        url: messageUrl(ref),
        method: 'PATCH',
        params: { folder: ref.folder },
        body: ref.patch,
      }),
      // 'Message' не сбрасываем: повторное чтение письма снова пометило бы его прочитанным.
      invalidatesTags: ['Messages', 'Folders'],
    }),
    deleteMessage: build.mutation<undefined, MessageRef & { permanent?: boolean }>({
      query: (ref) => ({
        url: messageUrl(ref),
        method: 'DELETE',
        params: { folder: ref.folder, permanent: ref.permanent ?? false },
      }),
      invalidatesTags: ['Messages', 'Folders'],
    }),
    sendMessage: build.mutation<SendResult, { accountId: number; body: SendRequest }>({
      query: ({ accountId, body }) => ({
        url: `/mail/accounts/${String(accountId)}/send`,
        method: 'POST',
        body,
      }),
      invalidatesTags: ['Messages', 'Message', 'Folders'],
    }),
    saveDraft: build.mutation<DraftResult, { accountId: number; body: SendRequest }>({
      query: ({ accountId, body }) => ({
        url: `/mail/accounts/${String(accountId)}/drafts`,
        method: 'POST',
        body,
      }),
      invalidatesTags: ['Messages', 'Folders'],
    }),
  }),
});

export const {
  useListAccountsQuery,
  useConnectAccountMutation,
  useDisconnectAccountMutation,
  useListFoldersQuery,
  useListMessagesQuery,
  useGetMessageQuery,
  useUpdateMessageMutation,
  useDeleteMessageMutation,
  useSendMessageMutation,
  useSaveDraftMutation,
} = mailboxApi;
