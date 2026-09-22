import { useTranslation } from 'react-i18next';
import { caretLine, type QueryProblem } from '../model/query-problem';

/**
 * Признак черновика у края поля: напечатано, но не применено, и Enter применит.
 * Глазам — короткая метка, программе чтения с экрана — фраза целиком: поле ссылается
 * на неё через `aria-describedby`.
 */
export function PendingMark({ id }: { id: string }) {
  const { t } = useTranslation('tasks');

  return (
    <span
      id={id}
      className="pointer-events-none absolute right-1.5 rounded-mark bg-attention-soft px-1 text-label font-semibold text-attention"
    >
      <span aria-hidden="true">{t('filters.pendingShort')}</span>
      <span className="sr-only">{t('filters.pending')}</span>
    </span>
  );
}

/**
 * Что сказал бэкенд о негодном отборе: фраза по коду, место в строке и допустимое.
 * Позиция называется и словами, и указателем: указатель виден глазами, слова
 * читаются программой чтения с экрана.
 */
export function QueryProblemHint({ id, problem }: { id: string; problem: QueryProblem }) {
  /*
   * `useTranslation` нужен и ради подписки: `problem.message` собран `errorText`,
   * а тот берёт язык у экземпляра и на смену языка не подписан.
   */
  const { t } = useTranslation('tasks');

  return (
    /*
     * Объяснение отказа наложено на страницу, а не встроено в поток формы: встроенное
     * уводило бы таблицу вниз на две сотни пикселей ровно в тот момент, когда человек
     * правит запрос и сверяется с прошлой выдачей.
     */
    <div
      className="absolute top-[calc(100%+var(--spacing))] left-0 z-5 flex max-w-160 min-w-full flex-col gap-2 rounded-mark border border-danger-line bg-danger-soft px-4 py-3 text-body text-danger shadow-raised"
      id={id}
      role="alert"
    >
      {/* Две фразы подряд, а не одна склеенная: отказ пришёл от бэкенда по коду,
          а место ошибки называем мы. */}
      <p>
        {problem.message}
        {problem.position === null
          ? null
          : ` ${t('filters.query.errorAt', { position: problem.position + 1 })}`}
      </p>

      {/* Без лигатур: `>=`, склеенный в один знак, сдвинул бы указатель на символ. */}
      {problem.position === null || problem.query === '' ? null : (
        <pre
          className="overflow-x-auto font-mono text-meta leading-[1.2] whitespace-pre [font-variant-ligatures:none]"
          aria-hidden="true"
        >
          {`${problem.query}\n${caretLine(problem.query, problem.position)}`}
        </pre>
      )}

      {problem.allowed.length === 0 ? null : (
        <p>{t('filters.query.allowed', { list: problem.allowed.join(', ') })}</p>
      )}

      {/* Таблица под формой продолжает показывать прошлую удачную выдачу; сказать
          об этом надо здесь, у отказа, а не полосой над таблицей, которая её сдвинет. */}
      <p>{t('filters.query.stale')}</p>
    </div>
  );
}
