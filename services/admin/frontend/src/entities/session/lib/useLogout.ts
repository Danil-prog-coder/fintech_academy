import { useNavigate } from 'react-router';

import { baseApi } from '@/shared/api';
import { routePaths } from '@/shared/config';
import { useAppDispatch } from '@/shared/lib/store';

import { useLogoutMutation } from '../api/sessionApi';

/** Выход из аккаунта сайта: сессия закрывается на сервере, кэш запросов очищается. */
export const useLogout = () => {
  const [logout] = useLogoutMutation();
  const navigate = useNavigate();
  const dispatch = useAppDispatch();
  return async () => {
    try {
      await logout(undefined).unwrap();
    } finally {
      dispatch(baseApi.util.resetApiState());
      void navigate(routePaths.login, { replace: true });
    }
  };
};
