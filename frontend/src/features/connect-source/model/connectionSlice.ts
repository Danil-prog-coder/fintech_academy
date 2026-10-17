import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

export type ConnectionStatus =
  | 'not_connected'
  | 'connecting'
  | 'reauthorizing'
  | 'connected'
  | 'auth_required'
  | 'forbidden'
  | 'error';

export type ConnectionKind = 'mail' | 'documents';

interface ConnectionState {
  mail: ConnectionStatus;
  documents: ConnectionStatus;
  /** Политика организации: разрешено ли подключение к внешнему приложению. */
  policy: 'allowed' | 'forbidden';
}

const initialState: ConnectionState = {
  mail: 'not_connected',
  documents: 'not_connected',
  policy: 'allowed',
};

export const connectionSlice = createSlice({
  name: 'connection',
  initialState,
  reducers: {
    connectionStatusChanged: (
      state,
      action: PayloadAction<{ kind: ConnectionKind; status: ConnectionStatus }>,
    ) => {
      state[action.payload.kind] = action.payload.status;
    },
    connectionsRestored: (state, action: PayloadAction<Partial<ConnectionState>>) => ({
      ...state,
      ...action.payload,
    }),
  },
  selectors: {
    selectMailConnection: (state) => state.mail,
    selectDocumentsConnection: (state) => state.documents,
    selectConnectionPolicy: (state) => state.policy,
    /** AI-функции доступны только при рабочем подключении почты. */
    selectAiAvailable: (state) => state.mail === 'connected',
  },
});

export const { connectionStatusChanged, connectionsRestored } = connectionSlice.actions;

export const {
  selectMailConnection,
  selectDocumentsConnection,
  selectConnectionPolicy,
  selectAiAvailable,
} = connectionSlice.selectors;
