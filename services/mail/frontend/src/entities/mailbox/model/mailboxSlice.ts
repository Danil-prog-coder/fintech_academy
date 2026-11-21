import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

export const PAGE_SIZE = 30;

interface MailboxState {
  accountId: number | null;
  folder: string;
  unreadOnly: boolean;
  query: string;
  page: number;
  selectedUid: number | null;
}

const initialState: MailboxState = {
  accountId: null,
  folder: 'INBOX',
  unreadOnly: false,
  query: '',
  page: 0,
  selectedUid: null,
};

const resetView = (state: MailboxState) => {
  state.page = 0;
  state.selectedUid = null;
};

export const mailboxSlice = createSlice({
  name: 'mailbox',
  initialState,
  reducers: {
    accountSelected: (state, action: PayloadAction<number | null>) => {
      state.accountId = action.payload;
      state.folder = initialState.folder;
      state.query = '';
      resetView(state);
    },
    folderSelected: (state, action: PayloadAction<string>) => {
      state.folder = action.payload;
      state.query = '';
      resetView(state);
    },
    unreadOnlyChanged: (state, action: PayloadAction<boolean>) => {
      state.unreadOnly = action.payload;
      resetView(state);
    },
    queryChanged: (state, action: PayloadAction<string>) => {
      state.query = action.payload;
      resetView(state);
    },
    pageChanged: (state, action: PayloadAction<number>) => {
      state.page = action.payload;
    },
    messageSelected: (state, action: PayloadAction<number | null>) => {
      state.selectedUid = action.payload;
    },
  },
  selectors: {
    selectAccountId: (state) => state.accountId,
    selectFolder: (state) => state.folder,
    selectUnreadOnly: (state) => state.unreadOnly,
    selectQuery: (state) => state.query,
    selectPage: (state) => state.page,
    selectSelectedUid: (state) => state.selectedUid,
  },
});

export const {
  accountSelected,
  folderSelected,
  unreadOnlyChanged,
  queryChanged,
  pageChanged,
  messageSelected,
} = mailboxSlice.actions;

export const {
  selectAccountId,
  selectFolder,
  selectUnreadOnly,
  selectQuery,
  selectPage,
  selectSelectedUid,
} = mailboxSlice.selectors;
