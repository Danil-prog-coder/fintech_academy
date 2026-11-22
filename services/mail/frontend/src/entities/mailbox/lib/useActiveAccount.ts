import { useAppSelector } from '@/shared/lib/store';

import { useListAccountsQuery } from '../api/mailboxApi';
import { selectAccountId } from '../model/mailboxSlice';

/** Выбранный ящик; если выбор устарел или не сделан — первый из подключённых. */
export const useActiveAccount = () => {
  const selectedId = useAppSelector(selectAccountId);
  const { data: accounts, isLoading, isError, refetch } = useListAccountsQuery(undefined);
  const account = accounts?.find((item) => item.id === selectedId) ?? accounts?.[0] ?? null;
  return { account, accounts: accounts ?? [], isLoading, isError, refetch };
};
