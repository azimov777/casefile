import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { knowledgeEntryHref, type EntryState } from '../model/state';
import type { EntryOwner } from '../model/owner';
import { DecisionStatusMark } from './decision-status';

/**
 * Пометка записи знания: плашка статуса и у заменённой — «→ <адрес преемника>» ссылкой
 * на него (TRK-660, TRK#59). Один компонент на описи «Дела» проекта и области и на
 * списки знания области: пометка выглядит везде одинаково.
 *
 * Действующая без `showInForce` ничего не рисует: в описи по двадцать записей подряд,
 * и «действует» у каждой — шум, а не сведение. Списки знания, где человек выбирает
 * действующее, плашку показывают всегда.
 */
export function EntryStateMark({
  owner,
  state,
  kind,
  showInForce = false,
}: {
  owner: EntryOwner;
  state: EntryState;
  kind: 'decision' | 'finding';
  showInForce?: boolean;
}) {
  const { t } = useTranslation('ui');
  if (state.status === 'in_force' && !showInForce) return null;
  const successor = state.supersededBy;

  return (
    <span className="inline-flex flex-wrap items-baseline gap-x-2 gap-y-1" data-entry-state>
      <DecisionStatusMark status={state.status} kind={kind} />
      {successor === null ? null : (
        <>
          <span aria-hidden="true" className="text-faint">
            →
          </span>
          <span className="sr-only">{t('decision.supersededBy')}</span>
          <Link to={knowledgeEntryHref(owner, successor)} className="font-mono whitespace-nowrap">
            {owner.key}#{successor}
          </Link>
        </>
      )}
    </span>
  );
}
