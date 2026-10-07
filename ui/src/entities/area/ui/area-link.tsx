import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { Signpost } from 'lucide-react';
import { cn, areaHref } from '@/shared/lib';

interface AreaLinkProps {
  address: string;
  title: string;
  /** Время архивации из контракта (`archived_at`); `null` — область в работе. */
  archivedAt?: string | null;
  className?: string;
}

/**
 * Область ссылкой на её страницу: знак, название и, у архивной, пометка словом.
 *
 * Знак — указатель: область говорит, «про что эта работа» (`../docs/CONCEPT.md`,
 * 3.7), и не путается ни с проектом, ни с родителем, которые стоят рядом в той же строке.
 * Диктору знак не нужен: имя ссылки начинается словом «область» (`sr-only`), а
 * пометка архива входит в имя, а не только в тон.
 */
export function AreaLink({ address, title, archivedAt = null, className }: AreaLinkProps) {
  const { t } = useTranslation('area');

  return (
    <Link
      to={areaHref(address)}
      className={cn('inline-flex items-baseline gap-1 wrap-anywhere', className)}
      data-area={address}
    >
      <Signpost className="size-(--ui-mark) shrink-0 self-center" aria-hidden="true" />
      <span className="sr-only">{t('mark.label')} </span>
      <span>{title}</span>
      {archivedAt === null ? null : (
        <span className="inline-block rounded-mark border border-dashed border-dropped-line px-1 text-label whitespace-nowrap text-dropped">
          {t('mark.archived')}
        </span>
      )}
    </Link>
  );
}
