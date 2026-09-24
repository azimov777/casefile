import { useTranslation } from 'react-i18next';
import type { Author } from '../api/entries';

/**
 * Кто говорит. Подпись пуста только у самого трекера: у человека и агента это имя
 * участника, у временного агента — метка. Различать метку и имя намеренно нельзя
 * (`docs/FRONTEND.md`), поэтому род показывается отдельной подписью.
 */
export function AuthorName({ author }: { author: Author }) {
  const signature = author.signature ?? null;
  const { t } = useTranslation('ui');

  return (
    <span className="inline-flex items-baseline gap-2 whitespace-nowrap">
      {/* Подпись — идентификатор контракта, и набрана она тем же, чем ключ задачи. */}
      <span className="font-mono">{signature ?? t('entry.tracker')}</span>
      {signature === null ? null : (
        <span className="text-label text-muted">{t(`participantKind.${author.kind}`)}</span>
      )}
    </span>
  );
}
