import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { Badge } from '@/shared/ui';
import { liftedByHref, type DraftState } from '../model/draft';

/**
 * Пометка черновика знания (TRK-661, TRK#57, §8): «Черновик в TRK/mcp — не поднят», пока
 * записи адресата со ссылкой на него нет, и «Поднят: TRK/mcp#5» ссылкой на неё — после.
 *
 * Тон внимания у неподнятого — знание осталось в закрытом деле, где его не найти, — и тон
 * «сделано» у поднятого. Слова несут смысл без цвета. Кнопки «поднять» нет: подъём делает
 * агент или человек обычной записью в деле адресата.
 */
export function DraftMark({ draft }: { draft: DraftState }) {
  const { t } = useTranslation('ui');
  const lifted = draft.liftedBy.length > 0;

  return (
    <span
      className="inline-flex flex-wrap items-baseline gap-x-2 gap-y-1"
      data-draft={lifted ? 'lifted' : 'open'}
    >
      {lifted ? (
        <>
          <Badge tone="positive">{t('draft.lifted')}</Badge>
          <span className="inline-flex flex-wrap gap-x-2 gap-y-1">
            {draft.liftedBy.map((reference) => {
              const href = liftedByHref(reference);
              return href === null ? (
                <span key={reference} className="font-mono whitespace-nowrap">
                  {reference}
                </span>
              ) : (
                <Link key={reference} to={href} className="font-mono whitespace-nowrap">
                  {reference}
                </Link>
              );
            })}
          </span>
        </>
      ) : (
        <Badge tone="attention">{t('draft.open', { address: draft.address })}</Badge>
      )}
    </span>
  );
}
