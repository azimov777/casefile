import { QueryClient } from '@tanstack/react-query';
import { ApiError } from '@/shared/api';

/**
 * Настройки серверного состояния.
 *
 * Отказ бэкенда с кодом 4xx не повторяется: это не сбой связи, а ответ по существу —
 * повтор даст тот же отказ и спрячет его за ожиданием. Перечитывания по фокусу окна
 * тоже нет: свежесть экрана обеспечивает живой поток (задача 07), а не догадки клиента.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: (failureCount, error) => {
          if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
          return failureCount < 2;
        },
        refetchOnWindowFocus: false,
      },
      mutations: { retry: false },
    },
  });
}
