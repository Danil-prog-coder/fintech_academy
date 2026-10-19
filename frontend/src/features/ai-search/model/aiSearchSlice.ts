import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

import { type SearchRequest } from './types';

interface AiSearchState {
  open: boolean;
  request: SearchRequest | null;
  /** Пользователь решил продолжить с неполными результатами. */
  caveatAccepted: boolean;
}

const initialState: AiSearchState = {
  open: false,
  request: null,
  caveatAccepted: false,
};

let nonce = 0;
const nextNonce = () => ++nonce;

export const aiSearchSlice = createSlice({
  name: 'aiSearch',
  initialState,
  reducers: {
    searchPanelToggled: (state) => {
      state.open = !state.open;
    },
    searchPanelOpened: (state) => {
      state.open = true;
    },
    /** Закрытие панели не затрагивает письмо и черновик. */
    searchPanelClosed: (state) => {
      state.open = false;
    },
    searchSubmitted: {
      reducer: (
        state,
        action: PayloadAction<{ query: string; refine: boolean; nonce: number }>,
      ) => {
        const { query, refine, nonce: requestNonce } = action.payload;
        const context =
          refine && state.request ? [...state.request.context, state.request.query] : [];
        state.request = { query, context, attempt: 0, nonce: requestNonce };
        state.caveatAccepted = false;
      },
      prepare: (payload: { query: string; refine?: boolean }) => ({
        payload: { query: payload.query, refine: payload.refine ?? false, nonce: nextNonce() },
      }),
    },
    searchRetried: (state) => {
      if (state.request) {
        state.request = {
          ...state.request,
          attempt: state.request.attempt + 1,
          nonce: nextNonce(),
        };
      }
    },
    searchReset: (state) => {
      state.request = null;
      state.caveatAccepted = false;
    },
    caveatAccepted: (state) => {
      state.caveatAccepted = true;
    },
    searchRestored: (state, action: PayloadAction<Partial<AiSearchState>>) => ({
      ...state,
      ...action.payload,
    }),
  },
  selectors: {
    selectSearchOpen: (state) => state.open,
    selectSearchRequest: (state) => state.request,
    selectCaveatAccepted: (state) => state.caveatAccepted,
  },
});

export const {
  searchPanelToggled,
  searchPanelOpened,
  searchPanelClosed,
  searchSubmitted,
  searchRetried,
  searchReset,
  caveatAccepted,
  searchRestored,
} = aiSearchSlice.actions;

export const { selectSearchOpen, selectSearchRequest, selectCaveatAccepted } =
  aiSearchSlice.selectors;
