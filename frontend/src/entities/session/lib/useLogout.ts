import { baseApi } from '@/shared/api';
import { useAppDispatch } from '@/shared/lib/store';
import { clearTokens } from '@/shared/lib/tokens';

/** Выход: удаляет токены и сбрасывает весь кэш запросов. */
export const useLogout = () => {
  const dispatch = useAppDispatch();
  return () => {
    clearTokens();
    dispatch(baseApi.util.resetApiState());
  };
};
