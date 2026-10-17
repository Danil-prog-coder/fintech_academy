import { createAsyncThunk } from '@reduxjs/toolkit';

import { delay } from '@/shared/lib/time';

import { connectionStatusChanged, type ConnectionKind } from './connectionSlice';

/**
 * Подключение источника через корпоративную учётную запись.
 * Если политика организации запрещает подключение, действие блокируется.
 */
export const connectSource = createAsyncThunk<undefined, ConnectionKind, { state: RootState }>(
  'connection/connect',
  async (kind, { dispatch, getState }) => {
    const reauth = getState().connection[kind] === 'auth_required';
    dispatch(connectionStatusChanged({ kind, status: reauth ? 'reauthorizing' : 'connecting' }));
    await delay(1400);
    const forbidden = getState().connection.policy === 'forbidden';
    dispatch(connectionStatusChanged({ kind, status: forbidden ? 'forbidden' : 'connected' }));
  },
  {
    condition: (kind, { getState }) => {
      const status = getState().connection[kind];
      return status !== 'connecting' && status !== 'reauthorizing';
    },
  },
);
