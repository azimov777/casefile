import { useTranslation } from 'react-i18next';
import type { components } from '@/shared/api';
import { Badge } from '@/shared/ui';

/** Действует ли запись знания: `in_force` или `superseded` (значение контракта). */
export type DecisionStatus = components['schemas']['DecisionStatus'];

/**
 * Статус записи знания плашкой: действует — тон «сделано», заменено — тон «снято»,
 * пунктиром и без заливки (`shared/ui/badge.tsx`). Статус считает бэкенд при чтении
 * (`../docs/CONCEPT.md`, 3.2); интерфейс его только показывает.
 *
 * Род значения («решение» или «заметка») стоит внутри плашки и попадает в её доступное
 * имя: рядом с ключом `TRK#15` одно слово «заменено» на слух не говорит, о чём оно.
 * Одна плашка на решения проекта, решения и заметки области и пометку в описи «Дела»
 * (TRK-660, TRK#59).
 */
export function DecisionStatusMark({
  status,
  kind = 'decision',
}: {
  status: DecisionStatus;
  kind?: 'decision' | 'finding';
}) {
  const { t } = useTranslation('ui');
  return (
    <Badge tone={status === 'in_force' ? 'positive' : 'dropped'} kind={t(`decision.kind.${kind}`)}>
      {t(`decision.status.${status}`)}
    </Badge>
  );
}
