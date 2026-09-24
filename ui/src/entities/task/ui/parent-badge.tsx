import { CornerLeftUp } from 'lucide-react';
import { Link, useLocation } from 'react-router';
import { Trans, useTranslation } from 'react-i18next';
import { Popover, PopoverContent, PopoverTrigger } from '@/shared/ui';
import { listReturnState, skipClickWhileSelecting, taskRefHref } from '@/shared/lib';
import type { TaskParent } from '../api/tasks';

interface ParentBadgeProps {
  /** Прямые родители из строки выдачи, в порядке появления связи. Пустой — плашки нет. */
  parents: readonly TaskParent[];
  /** Ключ самой задачи: панель называет, чей это родитель. */
  childKey: string;
}

/**
 * Родитель задачи плашкой в строке таблицы (UI-152, вариант владельца «б»): «родитель
 * DEMO-8». Стрелки на плашке нет: её место в гнезде дороже, чем знак, который повторяет
 * слово; стрелкой родители помечены в панели и на карточке доски. Строка держит высоту токеном, и полное «ключ · название» родителя рядом с
 * названием задачи урезало бы оба. Поэтому в строке только ключ, а целиком родитель
 * открывается нажатием — панелью, без наведения.
 *
 * **Слово «родитель» стоит и на плашке, и в заголовке панели.** Одна стрелка не говорит,
 * в какую сторону связь: владелец просил, чтобы не путалось, кто чей родитель. Поэтому
 * панель называет задачу строки по ключу: «Родитель задачи DEMO-9».
 *
 * Раскрытие — общий `Popover`, как у фильтров, а не свой механизм. Раскрыть смысл на
 * месте, как значок признака в шапке задачи (UI-163), здесь нельзя: строка от этого
 * выросла бы. Кнопка устроена так же, как там: рамку и фон браузера снимает явно, на
 * телефоне мишень не ниже `--ui-tap`.
 *
 * Панель рисуется в портале, но React ведёт всплытие по дереву компонентов, а не по DOM:
 * клик внутри панели дошёл бы до обработчика строки и увёл в саму задачу. Всплытие
 * остановлено на панели; ссылки в ней переходят сами.
 */
export function ParentBadge({ parents, childKey }: ParentBadgeProps) {
  const { t } = useTranslation('ui');
  const [first, ...others] = parents;

  if (first === undefined) return null;
  const many = others.length > 0;

  return (
    <Popover>
      <PopoverTrigger
        data-mark="parents"
        className="inline-flex max-w-full min-w-0 cursor-pointer items-center gap-1 rounded-mark border border-line bg-sunken px-1.5 py-0 text-mark leading-[1.5] whitespace-nowrap text-muted hover:border-line-strong hover:text-text max-fold:min-h-(--ui-tap)"
      >
        <span className="shrink-0">
          {t(many ? 'task.parents.badgeMany' : 'task.parents.badge')}
        </span>
        <span className="min-w-0 truncate font-mono">{first.key}</span>
        {many ? (
          <span className="shrink-0">{t('task.parents.more', { count: others.length })}</span>
        ) : null}
      </PopoverTrigger>
      <PopoverContent
        className="w-80 p-3"
        onClick={(event) => event.stopPropagation()}
        onAuxClick={(event) => event.stopPropagation()}
      >
        <ParentPanel parents={parents} childKey={childKey} />
      </PopoverContent>
    </Popover>
  );
}

/**
 * Содержимое панели плашки: чей это родитель и родители ссылками. Отдельно от `Popover`,
 * чтобы проверять его модульным тестом без слоя: панель Radix в jsdom раскрывается
 * десятки секунд (`docs/notes/testing.md`). Открытие и клик сквозь портал проверяет
 * `e2e/parents.spec.ts`.
 */
export function ParentPanel({ parents, childKey }: ParentBadgeProps) {
  const { search } = useLocation();
  const { t } = useTranslation('ui');
  const many = parents.length > 1;

  return (
    <>
      <p className="mt-0 mb-1.5 text-meta text-muted">
        <Trans
          t={t}
          i18nKey={many ? 'task.parents.headingMany' : 'task.parents.heading'}
          values={{ key: childKey }}
          components={{ key: <span className="font-mono" /> }}
        />
      </p>
      <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
        {parents.map((parent) => (
          <li key={parent.key} className="flex items-baseline gap-1">
            <CornerLeftUp
              className="size-(--ui-mark) shrink-0 self-center text-muted"
              aria-hidden="true"
            />
            <Link
              className="min-w-0 text-text no-underline wrap-anywhere [-webkit-user-drag:none] hover:underline"
              to={taskRefHref({ key: parent.key, entryNo: null })}
              // Отбор списка едет и в родителя: оттуда человек вернётся к тем же строкам.
              state={listReturnState(search)}
              draggable={false}
              onClick={skipClickWhileSelecting}
            >
              <Trans
                t={t}
                i18nKey="task.parents.caption"
                values={{ key: parent.key, title: parent.title }}
                components={{ key: <span className="font-mono" /> }}
              />
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}
