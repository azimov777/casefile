import type { TFunction } from 'i18next';
import type { Headline, HeadlinePart } from './headline';

/**
 * Что нужно от записи, чтобы положить её в группу: и строка описи (`EntryHeading`), и
 * запись ленты (`Entry`) это несут, поэтому одна функция служит обоим экранам.
 */
interface Groupable {
  no: number;
  type: string;
  action_id?: string | null;
}

/**
 * Кусок дела по порядку: либо одна запись, либо правки разделов одного действия.
 *
 * `first`/`last` — номера крайних записей группы: ими группа называется (`#6–12`), и
 * по первому из них её узнают между рендерами.
 */
export type SectionEditsRun<T> =
  | { kind: 'one'; item: T }
  | { kind: 'sections'; actionId: string; first: number; last: number; items: T[] };

/**
 * Правки разделов одного действия — одной группой, остальное — по одной записи.
 *
 * Действие называет контракт: `action_id` у записей одного вызова один и тот же
 * (`../openapi.json`, `EntryHeadingRead.action_id`, TRK-118). Совпавшее время — не
 * признак, и здесь оно не читается.
 *
 * В группу идут только `section_changed`, стоящие подряд: одним `update_task` агент
 * переписывает задание целиком, и семь пар «было / стало» подряд топили соседние
 * записи (UI-133). Остальные записи того же действия — `status_changed` перехода,
 * сводка и вердикты `close_task`, `field_changed` приоритета — остаются на своих местах:
 * их спрятать значило бы утопить в служебной группе то, ради чего дело читают.
 *
 * Одна правка группой не становится: группа из одной записи — лишний клик. `null`
 * (записи до появления признака) не группируется никогда: два `null` — не одно действие.
 */
export function groupSectionEdits<T extends Groupable>(items: readonly T[]): SectionEditsRun<T>[] {
  const runs: SectionEditsRun<T>[] = [];
  let pending: T[] = [];

  const flush = () => {
    const [head] = pending;
    const tail = pending.at(-1);
    if (pending.length > 1 && head?.action_id != null && tail !== undefined) {
      runs.push({
        kind: 'sections',
        actionId: head.action_id,
        first: head.no,
        last: tail.no,
        items: pending,
      });
    } else {
      for (const item of pending) runs.push({ kind: 'one', item });
    }
    pending = [];
  };

  for (const item of items) {
    const joins =
      item.type === 'section_changed' &&
      item.action_id != null &&
      pending[0]?.action_id === item.action_id;
    if (!joins) flush();
    if (item.type === 'section_changed' && item.action_id != null) pending.push(item);
    else runs.push({ kind: 'one', item });
  }
  flush();

  return runs;
}

/**
 * Заголовок группы: «Правка разделов» и имена разделов как есть, моноширинными.
 *
 * Имена не переводятся по той же причине, что у одной правки (`entryHeadline`): это
 * идентификаторы контракта. Раздел, правленный дважды (точечные правки двух проверок),
 * называется один раз — строка говорит, **что** тронуто, а сколько записей, видно по
 * номерам группы.
 */
export function sectionEditsHeadline(
  fields: readonly (string | null | undefined)[],
  t: TFunction<'ui'>,
): Headline {
  const named = [...new Set(fields.filter((field): field is string => field != null))];
  const parts: HeadlinePart[] = [
    { kind: 'words', text: t('entry.headline.sectionsEdited') },
    ...named.map((field): HeadlinePart => ({ kind: 'id', text: field })),
  ];
  return { kind: 'built', parts };
}
