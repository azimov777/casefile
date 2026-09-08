import type { ReactNode } from 'react';
import { errorMessage } from '../errors';
import { Button } from './button';
import { Callout } from './callout';

/**
 * Столько от результата `useQuery`, сколько нужно состоянию. Структурный тип, а не
 * `UseQueryResult`: кирпичу незачем знать про TanStack Query и её дженерики, а любой
 * результат запроса подходит сюда как есть.
 */
export interface QueryLike {
  /** Первый ответ ещё не пришёл: показывать нечего. */
  isPending: boolean;
  /** Запрос идёт — в том числе повтор после отказа. */
  isFetching: boolean;
  /** Отказ последнего запроса. */
  error: unknown;
  refetch: () => unknown;
}

interface QueryStateProps {
  query: QueryLike;
  /** Что именно грузим: спиннер без текста состоянием не считается (`CONVENTIONS.md`). */
  loading: string;
  /**
   * Честная пустота: текст, который видно, когда запрос удался, а показывать нечего.
   * Передаётся только в этом случае — знает об этом вызывающий, а не кирпич: «пусто»
   * у списка, у описи и у связей выражается по-разному.
   */
  empty?: ReactNode;
  /** Строкой, без рамки: там, где рамке негде развернуться, — например в шапке. */
  compact?: boolean;
}

/** Приглушённая строка: загрузка и пустота там, где рамке негде развернуться. */
const QUIET = 'text-meta text-muted';

/**
 * Состояние запроса вместо данных: загрузка, отказ с повтором, честная пустота.
 * Когда показывать нечего — возвращает `null` и не занимает места.
 *
 * Повтор зовёт `refetch`, а не перезагружает страницу: человек не теряет ни введённого,
 * ни того, на что смотрел на соседней половине экрана.
 */
export function QueryState({ query, loading, empty, compact = false }: QueryStateProps) {
  if (query.error !== null && query.error !== undefined) {
    return (
      // Строкой: в шапке высота фиксирована, и рамка сообщения разъехалась бы с ней.
      <div className={compact ? 'flex items-center gap-2' : 'flex flex-col items-start gap-2'}>
        {compact ? (
          <span className="text-meta text-danger" role="alert">
            {errorMessage(query.error)}
          </span>
        ) : (
          <Callout tone="danger">{errorMessage(query.error)}</Callout>
        )}
        <Button tone="quiet" onClick={() => void query.refetch()} disabled={query.isFetching}>
          {query.isFetching ? 'Повторяем…' : 'Повторить'}
        </Button>
      </div>
    );
  }

  if (query.isPending) {
    return compact ? <span className={QUIET}>{loading}</span> : <Callout>{loading}</Callout>;
  }

  if (empty === undefined) return null;
  return compact ? <span className={QUIET}>{empty}</span> : <Callout>{empty}</Callout>;
}
