import { CornerLeftUp } from 'lucide-react';
import { Link, useLocation } from 'react-router';
import { Trans, useTranslation } from 'react-i18next';
import { cn, listReturnState, skipClickWhileSelecting, taskRefHref } from '@/shared/lib';
import type { TaskParent } from '../api/tasks';

interface TaskParentsProps {
  /** Прямые родители из строки выдачи, в порядке появления связи. Пустой — подписи нет. */
  parents: readonly TaskParent[];
  /**
   * Поднять ссылку и число над растянутой ссылкой карточки. Нужно только карточке:
   * у строки таблицы растяжки нет (UI-39), и поднимать там не над чем.
   */
  raised?: boolean;
  /** Место подписи в раскладке того, кто её ставит: ширина, отступ, сжатие. */
  className?: string;
  /**
   * Там, где строка таблицы стала карточкой (`@max-list:`, телефон), подпись
   * переносится, а не режется многоточием (UI-153): полное название родителя было
   * только в подсказке `title`, а наведения на телефоне нет. Нужно только строке
   * таблицы: карточка доски держит подпись в одну строку (UI-115).
   */
  wrapNarrow?: boolean;
}

/**
 * Родитель задачи подписью в одну строку: «ключ · название» ссылкой в него (UI-119).
 * Карточка доски ставит подпись над ключом, строка списка — в ячейку названия, справа.
 *
 * Ничего не вычисляется и не догружается: `parents` приходит в строке выдачи (TRK-95),
 * родители всей страницы — тем же запросом, что и сама страница (`docs/FRONTEND.md`,
 * «`parents`»). Запроса за карточкой родителя здесь нет и быть не должно.
 *
 * **Родителей бывает несколько**, и молча брать первого нельзя: второй пропал бы, не
 * оставив следа. Ссылкой становится первый, то есть самый ранний по связи. Обычно это
 * программа, в которой задача родилась, и на странице задачи он стоит первым среди
 * `child`. Остальные сказаны числом «+N» рядом с ним. Поимённо их называет подсказка:
 * одна и та же у ссылки и у числа, все родители по строке. Для программы чтения с
 * экрана то же самое сказано скрытым текстом при числе. Число не усекается никогда:
 * многоточие съедает название первого родителя, но не сведения о том, что родителей
 * больше. Одним кликом из подписи достижим только первый; остальные — на странице
 * задачи, в блоке связей, куда ведёт клик по самой карточке.
 *
 * Подпись в одну строку, с многоточием и полным текстом в подсказке: карточка не должна
 * расти от длинного названия, а столбец доски — шириться от слова с путём (UI-115).
 * Поэтому у ссылки `min-w-0`: без него флекс-элемент не сжимается меньше своего
 * содержимого, а содержимое под `nowrap` длиной во всё название.
 *
 * Подсказка — путь только для мыши. Без наведения полный текст достижим нажатием: ссылка
 * ведёт в родителя, и там его название — заголовок страницы, а «+N» ведёт в саму задачу,
 * где все родители названы в блоке связей. В строке таблицы на телефоне подпись к тому же
 * переносится целиком (`wrapNarrow`, UI-153).
 */
export function TaskParents({
  parents,
  raised = false,
  className,
  wrapNarrow = false,
}: TaskParentsProps) {
  const { search } = useLocation();
  const { t } = useTranslation('ui');
  const [first, ...others] = parents;

  // Задача верхнего уровня: ни пустой строки, ни заглушки — подписи просто нет.
  if (first === undefined) return null;

  const item = (parent: TaskParent) =>
    t('task.parents.item', { key: parent.key, title: parent.title });
  // Подсказка называет всех, по родителю на строку: ей одной видно усечённое.
  const everyone = parents.map(item).join('\n');

  /*
   * Поднятое над растяжкой карточки (`relative z-1`) получает свой клик и свою
   * подсказку, но мишенью задачи быть перестаёт: цена приёма названа заметкой
   * «Растянутая ссылка: мишень надо делить» в `docs/notes/ui.md`. Поднята ровно
   * ссылка и число — строка подписи целиком не поднята, и пустое место справа от
   * короткой подписи по-прежнему ведёт в саму задачу. Знак слева тоже не поднят.
   */
  const lift = raised ? 'relative z-1' : undefined;

  return (
    <span
      data-mark="parents"
      className={cn(
        'flex min-w-0 items-center gap-1 text-meta text-muted',
        wrapNarrow && '@max-list:items-baseline',
        className,
      )}
    >
      <CornerLeftUp className="size-(--ui-mark) shrink-0" aria-hidden="true" />
      <Link
        /*
         * Цвет подписи, а не ссылки: подпись объясняет задачу и не должна спорить
         * с её названием. Ссылкой её делает подчёркивание под курсором и сам курсор.
         * Перетаскивание выключено по той же причине, что у названия: протяжка по
         * тексту выделяет его, а не таскает адрес.
         */
        className={cn(
          'min-w-0 truncate text-muted no-underline [-webkit-user-drag:none] hover:text-text hover:underline',
          wrapNarrow && '@max-list:whitespace-normal @max-list:wrap-anywhere',
          lift,
        )}
        to={taskRefHref({ key: first.key, entryNo: null })}
        // Отбор списка едет и в родителя: оттуда человек вернётся к тем же строкам.
        state={listReturnState(search)}
        title={everyone}
        draggable={false}
        onClick={skipClickWhileSelecting}
      >
        <span className="sr-only">{t('task.parents.label')} </span>
        <Trans
          t={t}
          i18nKey="task.parents.caption"
          values={{ key: first.key, title: first.title }}
          components={{ key: <span className="font-mono" /> }}
        />
      </Link>
      {others.length === 0 ? null : (
        <span className={cn('shrink-0', lift)} title={everyone}>
          <span aria-hidden="true">{t('task.parents.more', { count: others.length })}</span>
          <span className="sr-only">
            {t('task.parents.others', { count: others.length, parents: others.map(item) })}
          </span>
        </span>
      )}
    </span>
  );
}
