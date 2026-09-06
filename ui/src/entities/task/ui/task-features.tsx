import { Badge } from '@/shared/ui';
import type { TaskFeatures } from '../api/tasks';

/**
 * Признаки задачи значками. Ничего не вычисляет: `features` считает бэкенд, а интерфейс
 * не выдумывает за него (`CONCEPT.md`, 6).
 *
 * Живут в `entities/task`, потому что их рисуют и строка списка, и карточка: разъехавшись,
 * два представления одного и того же признака начали бы противоречить друг другу.
 */
export function TaskFeatureBadges({ features }: { features: TaskFeatures }) {
  return (
    <>
      {features.blocked ? (
        <Badge tone="danger" title="Есть связь blocked_by на незакрытую задачу">
          заблокирована
        </Badge>
      ) : null}

      {features.open_questions > 0 ? (
        <Badge tone="attention" title="Вопросы без ответа">
          вопросов {features.open_questions}
        </Badge>
      ) : null}

      {features.open_blocking_questions > 0 ? (
        <Badge tone="danger" title="Из них помечены blocking">
          блокирующих {features.open_blocking_questions}
        </Badge>
      ) : null}
    </>
  );
}
