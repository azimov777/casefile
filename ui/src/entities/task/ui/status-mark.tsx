import type { ReactElement } from 'react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/shared/lib';
import type { TaskStatus } from '../api/tasks';

/**
 * Форма статуса (решение Д1). Круг заполняется по мере продвижения: пунктирное кольцо
 * — ещё не взято, сплошное — взято, но пусто, половина — идёт работа, залитый круг
 * с галочкой — сделано. Две формы выпадают из шкалы намеренно: снятое не точка на
 * ней, а выход из неё, и перечёркивание говорит именно это; ожидание — тоже выход,
 * но временный, и пауза говорит именно это. Пауза, а не часы и не песочные часы:
 * `waiting` означает «работа остановлена, ход не за агентом», а не «идёт время».
 *
 * Различие держится без цвета: на чёрно-белом экране и у человека, не различающего
 * цвета, — это проверяет сквозной тест с `filter: grayscale(1)`.
 */
const STATUS_SHAPE = {
  backlog: <circle cx="12" cy="12" r="9" strokeDasharray="3 3.4" />,
  open: <circle cx="12" cy="12" r="9" />,
  in_progress: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 12V3a9 9 0 0 1 0 18Z" fill="currentColor" stroke="none" />
    </>
  ),
  done: (
    <>
      <circle cx="12" cy="12" r="10" fill="currentColor" stroke="none" />
      {/* Галка цвета поверхности: залитый круг — единственное исключение из
          «иконки одного семейства», и оно осмысленно — это конец шкалы. */}
      <path d="m7.6 12.4 3.1 3.1 5.7-6.6" stroke="var(--color-surface)" strokeWidth="2.2" />
    </>
  ),
  waiting: (
    <>
      <circle cx="12" cy="12" r="9" />
      {/* Две черты, а не три точки и не стрелки часов: при 14px просвет между ними
          выходит в полтора пикселя и переживает обесцвечивание, а точки диаметром
          меньше пикселя слились бы в серую полосу. */}
      <path d="M9.7 8.8v6.4" />
      <path d="M14.3 8.8v6.4" />
    </>
  ),
  cancelled: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M7.6 16.4 16.4 7.6" />
    </>
  ),
} satisfies Record<TaskStatus, ReactElement>;

/**
 * Цвет формы. Тот же словарь положений дел, что у тонов: `open` остаётся нейтральным
 * намеренно — открытых большинство, и покрасив их, цвет перестал бы что-либо значить.
 */
const SHAPE_COLOR = {
  backlog: 'text-faint',
  open: 'text-muted',
  in_progress: 'text-progress',
  waiting: 'text-attention',
  done: 'text-positive',
  cancelled: 'text-dropped',
} satisfies Record<TaskStatus, string>;

/**
 * Цвет имени. Служебного уровня здесь нет и быть не может: имя статуса — содержание
 * строки, его читают, и `axe` требует от него полного AA. Форме служебный уровень
 * позволен: она нетекстовая, и порог у неё 3.0.
 */
const NAME_COLOR = {
  backlog: 'text-muted',
  open: 'text-muted',
  in_progress: 'text-progress',
  waiting: 'text-attention',
  done: 'text-positive',
  cancelled: 'text-muted',
} satisfies Record<TaskStatus, string>;

function isKnown(status: string): status is TaskStatus {
  return status in STATUS_SHAPE;
}

interface StatusMarkProps {
  status: string | null | undefined;
  /**
   * Показывать ли имя рядом. Там, где места нет (карточка доски), оно не исчезает,
   * а уходит в доступное имя: иначе диктор прочёл бы пустоту.
   */
  withName?: boolean;
  /**
   * Говорить ли диктору род значения («статус», «приоритет») перед ним. Выключают там,
   * где род уже назван видимой подписью рядом — `dt` полосы свойств карточки (UI-143):
   * иначе диктор прочёл бы его дважды подряд.
   */
  labelled?: boolean;
  className?: string;
}

/** Статус задачи: форма, а не плашка. Имя из контракта стоит рядом моноширинным. */
export function StatusMark({
  status,
  withName = true,
  labelled = true,
  className,
}: StatusMarkProps) {
  const { t } = useTranslation('ui');

  if (status === null || status === undefined || status === '') return null;

  // Значение вне контракта не роняет отрисовку списка: показываем нейтральной формой.
  const known = isKnown(status);
  const shape = known ? STATUS_SHAPE[status] : STATUS_SHAPE.open;

  return (
    <span
      data-mark="status"
      className={cn('inline-flex items-center gap-1.5 whitespace-nowrap', className)}
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={cn('size-(--ui-mark) shrink-0', known ? SHAPE_COLOR[status] : 'text-muted')}
        aria-hidden="true"
      >
        {shape}
      </svg>
      {/* Пробел после подписи обязателен: диктор иначе прочёл бы «статусopen». */}
      {labelled ? <span className="sr-only">{t('task.statusLabel')} </span> : null}
      <span
        className={
          withName
            ? cn('font-mono text-mark', known ? NAME_COLOR[status] : 'text-muted')
            : 'sr-only'
        }
      >
        {status}
      </span>
    </span>
  );
}
