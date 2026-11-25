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
    }),
    updateMessage: build.mutation<undefined, MessageRef & { patch: MessagePatch }>({
      query: (ref) => ({
        url: messageUrl(ref),
        method: 'PATCH',
        params: { folder: ref.folder },
        body: ref.patch,
      }),
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

/*
 * Каждый запрос к почте — это новое IMAP-соединение с логином (Gmail отвечает за 0,5–1,5 с),
 * а список папок ещё и спрашивает STATUS у каждой папки. Поэтому флаги «прочитано»/«важное»
 * меняем в кэше сами, а список писем и папок перезапрашиваем, только когда письмо
 * действительно переехало (перемещение, удаление, отправка).
 */
type CacheState = Parameters<typeof mailboxApi.util.selectCachedArgsForQuery>[0];
type PatchAction = ReturnType<typeof mailboxApi.util.updateQueryData>;
type Dispatch = (action: PatchAction) => { undo: () => void };

const patchCachedFlags = (
  state: CacheState,
  dispatch: Dispatch,
  ref: MessageRef,
  patch: { seen?: boolean; flagged?: boolean },
): (() => void) => {
  const undo: (() => void)[] = [];
  let wasSeen: boolean | undefined;
  for (const args of mailboxApi.util.selectCachedArgsForQuery(state, 'listMessages')) {
    if (args.accountId !== ref.accountId || args.folder !== ref.folder) {
      continue;
    }
    undo.push(
      dispatch(
        mailboxApi.util.updateQueryData('listMessages', args, (draft) => {
          const item = draft.items.find((m) => m.uid === ref.uid);
          if (!item) {
            return;
          }
          wasSeen ??= item.seen;
          if (patch.seen !== undefined) {
            item.seen = patch.seen;
          }
          if (patch.flagged !== undefined) {
            item.flagged = patch.flagged;
          }
        }),
      ).undo,
    );
  }
  if (patch.seen !== undefined && wasSeen !== undefined && wasSeen !== patch.seen) {
    const delta = patch.seen ? -1 : 1;
    undo.push(
      dispatch(
        mailboxApi.util.updateQueryData('listFolders', ref.accountId, (draft) => {
          const folder = draft.find((f) => f.path === ref.folder);
          if (folder) {
            folder.unseen = Math.max(0, folder.unseen + delta);
          }
        }),
      ).undo,
    );
  }
  return () => {
    undo.forEach((fn) => {
      fn();
    });
  };
};

mailboxApi.enhanceEndpoints({
  endpoints: {
    getMessage: {
      // Чтение помечает письмо прочитанным на сервере: отражаем это в списке и счётчике
      // папки локально, без повторного запроса списка и папок.
      onQueryStarted: async (ref, lifecycle) => {
        const { dispatch, queryFulfilled } = lifecycle;
        try {
          await queryFulfilled;
          patchCachedFlags(lifecycle.getState(), dispatch, ref, { seen: true });
        } catch {
          // Ошибку покажет сам экран письма.
        }
      },
    },
    updateMessage: {
      // Флаги меняем в кэше сразу (и откатываем при ошибке); список и папки перезапрашиваем,
      // только если письмо переехало. 'Message' не сбрасываем: повторное чтение письма снова
      // пометило бы его прочитанным.
      onQueryStarted: async (arg, lifecycle) => {
        const { dispatch, queryFulfilled } = lifecycle;
        if (arg.patch.move_to) {
          return;
        }
        const undo = patchCachedFlags(lifecycle.getState(), dispatch, arg, arg.patch);
        try {
          await queryFulfilled;
        } catch {
          undo();
        }
      },
      invalidatesTags: (_result, error, arg) =>
        arg.patch.move_to || error ? ['Messages', 'Folders'] : [],
    },
  },
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
