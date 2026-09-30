import { useQuery } from '@tanstack/react-query';
import { bootstrapQueryOptions } from '@/entities/session';

/** Что человек вправе делать с проектом в этом сеансе. */
export interface ProjectRights {
  /** Завести проект, править название и описание, архивировать и восстановить. */
  manage: boolean;
  /** Атрибуты и заметки в дело проекта. */
  write: boolean;
}

/**
 * Права на проект в этом сеансе. Наборов токена больше нет (TRK-471): запись открыта
 * всем, кто вошёл, и решение `TRK-150#7` про набор `main` снято вместе с ними, — поэтому
 * хук `scope` не читает.
 *
 * Пока первый кадр не пришёл, прав нет никаких: кнопка, возникшая и исчезнувшая, хуже
 * поздней, и сеанс, которого ещё нет, ничего не пишет.
 */
export function useProjectRights(): ProjectRights {
  const bootstrap = useQuery(bootstrapQueryOptions());
  const known = bootstrap.data !== undefined;
  return { manage: known, write: known };
}
