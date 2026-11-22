import { useNavigate } from 'react-router';

import { baseApi } from '@/shared/api';
import { routePaths } from '@/shared/config';
import { useAppDispatch } from '@/shared/lib/store';

import { type Me } from '../api/sessionApi';

/**
 * Переход в проект после входа, создания, вступления или смены проекта. Кэш запросов сбрасывается целиком:
 * статистика, документы и обращения прежнего проекта не должны мелькнуть в новом.
 */
export const useEnterProject = () => {
  const dispatch = useAppDispatch();
  const navigate = useNavigate();
  return (me: Me) => {
    dispatch(baseApi.util.resetApiState());
    if (!me.project) {
      void navigate(routePaths.projects, { replace: true });
      return;
    }
    void navigate(me.role === 'support' ? routePaths.tickets : routePaths.root, { replace: true });
  };
};
