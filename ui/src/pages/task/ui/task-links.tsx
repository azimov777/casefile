import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import {
  LINK_KIND_ORDER,
  LinkKindMark,
  StatusMark,
  type LinkKind,
  type TaskLink,
} from '@/entities/task';

/**
 * Поля тела блока. Связи — список внутри поверхности карточки (решение Д11): у
 * блока-списка своих полей нет, иначе строки не доходили бы до краёв, и поля держит
 * тело. Одно на оба состояния — список и честное «связей нет»: пустое состояние без
 * них стояло вплотную к рамке и читалось как выпавшее из панели (UI-141).
 */
const BODY = 'p-3';

/**
 * Связи с обеих сторон, сгруппированные видом (UI-125). Вид назван от лица этой
 * задачи, статус связанной задачи — тем же знаком, что и в таблице задач
 * (`StatusMark`): именно из `blocked_by` на незакрытую задачу бэкенд считает
 * признак «заблокирована».
 *
 * Группа — заголовок вида со счётчиком, под ним список задач этого вида. Прежде вид
 * был узкой плашкой слева от общего столбика всех связей: она резала длинный
 * идентификатор до «rel…», «bloc…», «pa…» и не говорила, где кончается одна связь
 * и начинается другая. Второй раскладки не осталось — эта заменяет прежнюю целиком.
 */
export function TaskLinks({ links }: { links: TaskLink[] }) {
  const { t } = useTranslation('task');

  if (links.length === 0) {
    return (
      <div className={BODY}>
        <p className="text-muted italic">{t('noLinks')}</p>
      </div>
    );
  }

  const byKind = new Map<LinkKind, TaskLink[]>();
  for (const link of links) {
    const same = byKind.get(link.kind) ?? [];
    same.push(link);
    byKind.set(link.kind, same);
  }

  return (
    /*
     * Одна сетка на весь блок, два столбца: ключ и всё остальное (UI-148). Группы,
     * списки и строки — её подсетки (`subgrid`), поэтому столбец ключа один на все
     * связи блока: ширину ему задаёт самый длинный ключ, и название с отметкой
     * статуса у всех строк начинаются с одного и того же края.
     *
     * Прежде строка была гибким рядом с переносом: короткое название вставало рядом
     * с ключом и статусом в одну линию, длинное — ключ, название и статус тремя
     * строками, а зазор между связями (4 px) был меньше зазора внутри связи (8 px), и
     * статус одной связи читался вместе с ключом следующей. Теперь у каждой строки
     * одна форма: ключ слева, название справа от него переносится в своём столбце,
     * статус всегда под названием. Граница между связями — линия и поле с обеих её
     * сторон: вместе они больше любого зазора внутри строки.
     */
    <div className={`grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-5 ${BODY}`}>
      {LINK_KIND_ORDER.filter((kind) => byKind.has(kind)).map((kind) => {
        // Непусто по самому фильтру строкой выше: `byKind.has(kind)` уже это проверил.
        const group = byKind.get(kind) as TaskLink[];

        return (
          <section key={kind} className="col-span-2 grid grid-cols-subgrid gap-y-2">
            {/*
             * Заголовок группы — вид связи, а не число: счётчик стоит рядом с ним,
             * а не выносится в отдельную строку, иначе на узком экране он читался
             * бы как ещё одна, третья строка. `LinkKindMark` не обрезает идентификатор
             * контракта (`ui/docs/CONCEPT.md`, 6) — он остаётся моноширинным целиком.
             */}
            <h3 className="col-span-2 flex flex-wrap items-baseline gap-2">
              <LinkKindMark kind={kind} />
              <span className="text-meta text-muted">
                {t('linkGroup.count', { count: group.length })}
              </span>
            </h3>
            <ul className="col-span-2 grid list-none grid-cols-subgrid divide-y divide-line p-0">
              {group.map((link) => (
                /*
                 * Ключ и название стоят на одной базовой линии первой строки; статус —
                 * во второй, под названием, у любой длины названия. Название
                 * переносится в своём столбце и не обрезается (`ui/docs/CONCEPT.md`, 6).
                 */
                <li
                  key={link.other.key}
                  className="col-span-2 grid grid-cols-subgrid items-baseline gap-y-1 py-2 first:pt-0 last:pb-0"
                >
                  <Link className="font-mono" to={`/tasks/${link.other.key}`}>
                    {link.other.key}
                  </Link>
                  <span className="min-w-0 break-words text-muted">{link.other.title}</span>
                  <StatusMark className="col-start-2" status={link.other.status} />
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
