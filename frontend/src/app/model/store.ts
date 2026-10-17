import { combineReducers, configureStore } from '@reduxjs/toolkit';

import { baseApi } from '@/shared/api';

const rootReducer = combineReducers({
  [baseApi.reducerPath]: baseApi.reducer,
  // Регистрируйте здесь редьюсеры слайсов: entities, features и т.д.
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
