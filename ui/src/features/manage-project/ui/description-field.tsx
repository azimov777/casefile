import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { PROJECT_DESCRIPTION_LIMIT, descriptionLength } from '@/entities/project';
import { Textarea } from '@/shared/ui';

/**
 * Поле описания проекта или области с остатком до предела (`PROJECT_DESCRIPTION_LIMIT`
 * у проекта, `AREA_DESCRIPTION_LIMIT` у области — `limit`). Длину оба бэкенд
 * меряет одинаково (`descriptionLength`), различаются предел и подсказка.
 *
 * Остаток — единственное, что окно считает само (`UI-175`, ограничения): он виден,
 * пока человек пишет, а не после отказа. Сверх предела поле помечено отказом, а
 * остаток сменяется числом лишних знаков словами — отправку запрещает окно, но решает
 * по-прежнему бэкенд (`project_description_too_long`).
 *
 * Остаток не объявляется программе чтения с экрана на каждый знак — `aria-live` здесь
 * был бы потоком чисел поверх набора. Он связан с полем `aria-describedby` и читается,
 * когда человек возвращается к полю; переход за предел объявляется один раз — строкой
 * `role="alert"`.
 */
export function DescriptionField({
  value,
  onChange,
  limit = PROJECT_DESCRIPTION_LIMIT,
  hint,
}: {
  value: string;
  onChange: (value: string) => void;
  limit?: number;
  /** Подсказка под полем: куда едет описание. Без неё — подсказка проекта. */
  hint?: string;
}) {
  const id = useId();
  const hintId = useId();
  const countId = useId();
  const { t } = useTranslation('project');

  const left = limit - descriptionLength(value);
  const over = left < 0;

  return (
    <div className="flex flex-col gap-1">
      <label className="text-meta text-muted" htmlFor={id}>
        {t('description.label')}
      </label>
      <Textarea
        id={id}
        rows={4}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={over}
        aria-describedby={`${hintId} ${countId}`}
      />
      <span className="text-meta text-muted" id={hintId}>
        {hint ?? t('description.hint')}
      </span>
      {over ? (
        <span className="text-meta text-danger" id={countId} role="alert">
          {t('description.over', { count: -left, limit })}
        </span>
      ) : (
        <span className="text-meta text-muted tabular-nums" id={countId}>
          {t('description.left', { count: left, limit })}
        </span>
      )}
    </div>
  );
}
