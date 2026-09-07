import type { ReactNode } from 'react';
import { Link, useLocation } from 'react-router';
import { caseHref, listReturnHref, taskRefHref } from '@/shared/lib';
import styles from './task-nav.module.css';

interface TaskNavProps {
  taskKey: string;
  /** Где человек сейчас: это меняет подсветку, а не набор ссылок. */
  view: 'card' | 'case';
  /**
   * Действие страницы — на карточке это «оставить замечание».
   *
   * Живёт здесь, потому что строка липкая: единственное, что человеку разрешено
   * начать самому, должно быть доступно с любой глубины прокрутки, а не лежать
   * за описью в сотню записей. Что именно это за действие, слой сущности не знает
   * и знать не должен.
   */
  action?: ReactNode;
}

/**
 * Возврат в список и переключение «Карточка — Дело» одной строкой над задачей.
 *
 * Липкая: дело бывает в тысячи пикселей длиной, и «уйти отсюда» должно быть доступно
 * с любой глубины прокрутки, а не только сверху. Раньше с карточки в дело вела ссылка
 * в заголовке блока «Дело» на 1300-м пикселе, а обратно — только кнопка браузера.
 *
 * Живёт в `entities/task`, потому что её показывают обе страницы задачи: разъехавшись,
 * два экземпляра одной и той же навигации начали бы вести в разные места.
 */
export function TaskNav({ taskKey, view, action }: TaskNavProps) {
  const location = useLocation();
  const back = listReturnHref(location.state);

  return (
    <nav className={styles.nav} aria-label={`Навигация по задаче ${taskKey}`}>
      {/*
       * Настоящая ссылка с адресом, а не `history.back()`: человек должен видеть,
       * куда попадёт, и мочь открыть это в новой вкладке. Когда отбора в памяти нет
       * — вход был прямой, — ссылка честно зовёт ко всем задачам и так и называется.
       */}
      <Link className={styles.back} to={back ?? '/tasks'}>
        {back === null ? '← Ко всем задачам' : '← К списку с отбором'}
      </Link>

      <span className={styles.right}>
        {action}

        <span className={styles.views}>
          {/*
           * Состояние перехода передаётся дальше: уйдя в дело и вернувшись, человек
           * не должен терять отбор, с которым пришёл из списка.
           */}
          <Link
            className={styles.view}
            to={taskRefHref({ key: taskKey, entryNo: null })}
            state={location.state}
            aria-current={view === 'card' ? 'page' : undefined}
          >
            Карточка
          </Link>
          <Link
            className={styles.view}
            to={caseHref(taskKey)}
            state={location.state}
            aria-current={view === 'case' ? 'page' : undefined}
          >
            Дело
          </Link>
        </span>
      </span>
    </nav>
  );
}
