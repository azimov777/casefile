import type { ReactNode } from 'react';
import { errorMessage } from '../errors';
import { Button } from './button';
import { Callout } from './callout';
import styles from './query-state.module.css';

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
      <div className={compact ? styles.compact : styles.failure}>
        {compact ? (
          <span className={styles.problem} role="alert">
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
    return compact ? <span className={styles.quiet}>{loading}</span> : <Callout>{loading}</Callout>;
  }

  if (empty === undefined) return null;
  return compact ? <span className={styles.quiet}>{empty}</span> : <Callout>{empty}</Callout>;
}
