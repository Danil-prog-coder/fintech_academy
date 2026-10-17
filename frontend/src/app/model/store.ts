import { combineReducers, configureStore } from '@reduxjs/toolkit';

import { draftSlice } from '@/entities/draft';
import { letterSlice } from '@/entities/letter';
import { aiSearchSlice } from '@/features/ai-search';
import { versionPickerSlice } from '@/features/choose-attachment-version';
import { connectionSlice } from '@/features/connect-source';
import { aiReplySlice } from '@/features/prepare-reply';
import { refineSlice } from '@/features/refine-reply';
import { baseApi } from '@/shared/api';

const rootReducer = combineReducers({
  [baseApi.reducerPath]: baseApi.reducer,
  [letterSlice.reducerPath]: letterSlice.reducer,
  [draftSlice.reducerPath]: draftSlice.reducer,
  [aiReplySlice.reducerPath]: aiReplySlice.reducer,
  [refineSlice.reducerPath]: refineSlice.reducer,
  [versionPickerSlice.reducerPath]: versionPickerSlice.reducer,
  [aiSearchSlice.reducerPath]: aiSearchSlice.reducer,
  [connectionSlice.reducerPath]: connectionSlice.reducer,
});

export const store = configureStore({
  reducer: rootReducer,
  middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(baseApi.middleware),
});

declare global {
  /** Глобальные типы стора, чтобы shared/lib/store не импортировал из app (запрещено FSD). */
  type RootState = ReturnType<typeof rootReducer>;
  type AppDispatch = typeof store.dispatch;
}
