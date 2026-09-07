import { TASK_COLUMNS, TaskRow, type Task } from '@/entities/task';

interface TasksTableProps {
  tasks: Task[];
  /** Показанное устарело: идёт запрос или последний был отклонён. */
  stale: boolean;
}

/**
 * Ширины колонок заданы здесь и не зависят от содержимого: при раскладке по
 * содержимому колонка «Теги» расширялась под самый длинный набор и отнимала ширину
 * у названия, а при листании сетка перекраивалась от страницы к странице. Название
 * забирает всё, что осталось.
 */
const WIDTHS = [
  'w-20', // Ключ — 80 px
  'w-auto', // Название — всё, что осталось
  'w-30', // Статус — 120 px
  'w-26', // Исполнитель — 104 px
  'w-24', // Приоритет — 96 px, было 94.8 по содержимому
  'w-36', // Теги — 144 px: два тега и счётчик
  'w-24', // Признаки — 96 px: три знака с числами
  'w-26', // Активность — 104 px
];

/**
 * Таблица списка. Заголовки берутся у представления строки: порядок ячеек и порядок
 * столбцов обязаны совпадать, и держать их в двух местах значило бы однажды разойтись.
 *
 * `overflow-x-clip`, а не `auto`: `auto` делает обёртку прокручиваемым предком, и
 * липкая шапка прилипала бы к ней — то есть уезжала бы вместе с ней за верх окна.
 * `clip` прокручиваемого предка не создаёт (`docs/notes/ui.md`).
 */
export function TasksTable({ tasks, stale }: TasksTableProps) {
  return (
    <div className="overflow-x-clip rounded-block border border-line bg-surface">
      <table className="w-full table-fixed border-collapse text-body" aria-busy={stale}>
        {/*
         * Подпись таблицы читается программой чтения с экрана, но места на экране не
         * занимает: то же число человек видит в строке управления, рядом с заголовком
         * страницы.
         */}
        <caption className="sr-only">Задач по отбору: {tasks.length}</caption>
        <thead>
          <tr>
            {TASK_COLUMNS.map((column, index) => (
              <th
                key={column}
                scope="col"
                /*
                 * Шапка держится у верха окна на любой глубине прокрутки: последние
                 * строки длинного списка читаются с подписанными колонками, а не
                 * наугад. Фон обязателен — у прилипшей ячейки нет своего, и строки
                 * просвечивали бы сквозь заголовок; нижняя граница нарисована тенью,
                 * потому что граница ячейки при `border-collapse` уезжает с прокруткой.
                 */
                className={`sticky top-0 z-1 h-(--ui-row-head) bg-surface px-3 text-left align-middle text-label font-semibold tracking-caps text-faint uppercase shadow-sticky ${WIDTHS[index] ?? ''} ${index === TASK_COLUMNS.length - 1 ? 'text-right' : ''}`}
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className={stale ? 'opacity-60' : undefined}>
          {tasks.map((task) => (
            <TaskRow key={task.key} task={task} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
