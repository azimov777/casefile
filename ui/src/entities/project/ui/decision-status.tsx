import { useTranslation } from 'react-i18next';
import { Badge } from '@/shared/ui';
import type { DecisionStatus } from '../api/project';

/**
 * Статус решения проекта плашкой: действует — тон «сделано», заменено — тон «снято»,
 * пунктиром и без заливки (`shared/ui/badge.tsx`). Статус считает бэкенд при чтении
 * (`../docs/CONCEPT.md`, 3.2); интерфейс его только показывает.
 *
 * Род значения («решение») стоит внутри плашки и попадает в её доступное имя: рядом с
 * ключом `TRK#15` одно слово «заменено» на слух не говорит, о чём оно.
 */
export function DecisionStatusMark({ status }: { status: DecisionStatus }) {
  const { t } = useTranslation('ui');
  return (
    <Badge tone={status === 'in_force' ? 'positive' : 'dropped'} kind={t('decision.kind')}>
      {t(`decision.status.${status}`)}
    </Badge>
  );
}
