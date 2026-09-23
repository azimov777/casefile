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
    <div className={`flex flex-col gap-4 ${BODY}`}>
      {LINK_KIND_ORDER.filter((kind) => byKind.has(kind)).map((kind) => {
        // Непусто по самому фильтру строкой выше: `byKind.has(kind)` уже это проверил.
        const group = byKind.get(kind) as TaskLink[];

        return (
          <section key={kind} className="flex flex-col gap-2">
            {/*
             * Заголовок группы — вид связи, а не число: счётчик стоит рядом с ним,
             * а не выносится в отдельную строку, иначе на узком экране он читался
             * бы как ещё одна, третья строка. `LinkKindMark` не обрезает идентификатор
             * контракта (`ui/docs/CONCEPT.md`, 6) — он остаётся моноширинным целиком.
             */}
            <h3 className="flex flex-wrap items-baseline gap-2">
              <LinkKindMark kind={kind} />
              <span className="text-meta text-muted">
                {t('linkGroup.count', { count: group.length })}
              </span>
            </h3>
            <ul className="flex list-none flex-col gap-1 p-0">
              {group.map((link) => (
                <li key={link.other.key} className="flex flex-wrap items-baseline gap-2">
                  <Link className="font-mono" to={`/tasks/${link.other.key}`}>
                    {link.other.key}
                  </Link>
                  <span className="text-muted">{link.other.title}</span>
                  <StatusMark status={link.other.status} />
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
