import { useTranslation } from 'react-i18next';
import { Badge } from '@/shared/ui';
import type { DiscussionStatus, DiscussionTurn } from '../api/discussions';

/**
 * Чей ход в обсуждении — словами и тоном (TRK#51, п. 4): ход за человеком — внимание,
 * за агентом — ход идёт, закрытое — нейтрально. Признак считает бэкенд (`turn`), здесь
 * он только читается: у открытого обсуждения без хода (`turn: null`) отметки нет.
 */
export function TurnMark({
  status,
  turn,
}: {
  status: DiscussionStatus;
  turn: DiscussionTurn | null;
}) {
  const { t } = useTranslation('discussions');

  if (status === 'closed') return <Badge tone="dropped">{t('turn.closed')}</Badge>;
  if (turn === 'human') return <Badge tone="attention">{t('turn.human')}</Badge>;
  if (turn === 'agent') return <Badge tone="progress">{t('turn.agent')}</Badge>;
  return <Badge tone="neutral">{t('turn.open')}</Badge>;
}
