import { useTranslation } from 'react-i18next';
import { Markdown, RelativeTime } from '@/shared/ui';
import type { Conclusion } from '@/entities/discussion';
import { discussionHref } from '@/shared/lib';
import { Link } from 'react-router';

/** Часть итога: подпись надстрочно и текст markdown, ссылки `TRK~7#3` в нём кликабельны. */
function Part({ title, value, tone }: { title: string; value: string; tone: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <h3 className={`text-label font-semibold tracking-caps uppercase ${tone}`}>{title}</h3>
      <div className="min-w-0 wrap-anywhere">
        <Markdown>{value}</Markdown>
      </div>
    </div>
  );
}

/**
 * Итог сверху: что решено, что заменено, что открыто. Его ведёт агент — человек итога не
 * пишет, и формы здесь нет. Последний итог главнее предыдущих; чьим он был и когда подшит,
 * сказано строкой над частями, со ссылкой на запись в переписке.
 */
export function ConclusionBox({
  address,
  conclusion,
}: {
  address: string;
  conclusion: Conclusion | null;
}) {
  const { t } = useTranslation('discussions');
  const { t: brick } = useTranslation('ui');

  if (conclusion === null) {
    return <p className="m-0 text-muted italic">{t('conclusion.none')}</p>;
  }

  return (
    <div className="flex flex-col gap-3" data-conclusion={conclusion.no}>
      <p className="m-0 flex flex-wrap items-baseline gap-x-3 text-meta text-muted">
        <Link className="font-mono whitespace-nowrap" to={discussionHref(address, conclusion.no)}>
          {address}#{conclusion.no}
        </Link>
        <span>{conclusion.author.signature ?? t('page.tracker')}</span>
        <RelativeTime value={conclusion.created_at} />
      </p>
      <div className="grid gap-4 wide:grid-cols-3">
        <Part
          title={brick('entry.conclusion.decided')}
          value={conclusion.payload.decided}
          tone="text-positive"
        />
        <Part
          title={brick('entry.conclusion.superseded')}
          value={conclusion.payload.superseded}
          tone="text-muted"
        />
        <Part
          title={brick('entry.conclusion.open')}
          value={conclusion.payload.open}
          tone="text-attention"
        />
      </div>
    </div>
  );
}
