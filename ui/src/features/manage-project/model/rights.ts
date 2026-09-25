import { useQuery } from '@tanstack/react-query';
import { bootstrapQueryOptions } from '@/entities/session';

/** Что человек вправе делать с проектом этим ключом. */
export interface ProjectRights {
  /** Завести проект, править название и описание, архивировать и восстановить: набор `main`. */
  manage: boolean;
  /** Атрибуты и заметки в дело проекта: любой набор, `task` тоже. */
  write: boolean;
}

/**
 * Права на проект по набору ключа этого сеанса (`bootstrap.token.scope`, TRK-65;
 * решение 7 `TRK-150`, `../docs/CONCEPT.md`, 3.2).
 *
 * Действие, которого набор не даёт, не рисуется вовсе, а не стоит запрещённой кнопкой:
 * на уровне проекта `task` — обычный ключ человека с чужой установки, и кнопка,
 * которая наверняка кончится `403`, для него ловушка, а не подсказка. Пока первый кадр
 * не пришёл, прав нет никаких: кнопка, возникшая и исчезнувшая, хуже поздней.
 */
export function useProjectRights(): ProjectRights {
  const bootstrap = useQuery(bootstrapQueryOptions());
  const scope = bootstrap.data?.token.scope;
  return { manage: scope === 'main', write: scope !== undefined };
}
