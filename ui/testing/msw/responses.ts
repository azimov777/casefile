import { HttpResponse } from 'msw';
import type { components } from '@/shared/api';

/** Источник, на который ходит приложение в тестах (см. `env` в vite.config.ts). */
export const API = 'http://localhost:3000';

type Bootstrap = components['schemas']['BootstrapRead'];

/** Ответ-ресурс в оболочке контракта. */
export function data<T>(payload: T, status = 200) {
  return HttpResponse.json({ data: payload }, { status });
}

/** Отказ в оболочке контракта. */
export function failure(
  code: string,
  status: number,
  message = 'Error',
  details: Record<string, unknown> = {},
) {
  return HttpResponse.json({ error: { code, message, details } }, { status });
}

const AUTHOR = { kind: 'tracker', signature: null } as const;
const STAMPS = { created_at: '2026-09-01T10:00:00Z', updated_at: '2026-09-01T10:00:00Z' };

export function bootstrap(overrides: Partial<Bootstrap> = {}): Bootstrap {
  return {
    participant: {
      id: '11111111-1111-1111-1111-111111111111',
      kind: 'human',
      name: 'owner',
      description: 'Владелец установки',
      created_by: AUTHOR,
      ...STAMPS,
    },
    queues: [
      {
        id: '22222222-2222-2222-2222-222222222222',
        key: 'DEMO',
        title: 'Демонстрация',
        description: '',
        last_task_number: 7,
        created_by: AUTHOR,
        ...STAMPS,
      },
    ],
    open_questions: 2,
    ...overrides,
  };
}
