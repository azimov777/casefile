# src/entities/task

Задача: типы из контракта, запрос списка и представление одной строки. Признаки
(`blocked`, счётчики вопросов, время последней сводки) и прямые родители (`parents`)
приезжают в самой строке выдачи, поэтому запроса на задачу отсюда нет.

## Папки

- `api/` — `tasks.ts`: параметры отбора, запросы списка, столбца доски и числа выдачи,
  ключи запросов двумя префиксами (`taskKeys.table` и `taskKeys.board`: по ним живой поток
  различает экраны), наборы значений; правило архива складывается с отбором в момент чтения
- `model/` — архив: закрытые задачи без записей в деле дольше порога — правило представления,
  которое уходит бэкенду строкой языка запросов (UI-97)
- `ui/` — строка таблицы и заголовки её столбцов, карточка доски, подпись родителя, знаки

## Файлы

- `index.ts` — публичный интерфейс среза: `tasksQueryOptions`, `tasksColumnQueryOptions`,
  `tasksTotalQueryOptions`, `fetchTasks`, `taskKeys`, `TASK_STATUSES`, `TASK_PRIORITIES`,
  `TASK_LIST_FIELDS`, `TASK_PAGE_SIZE`, `TASK_COLUMN_PAGE_SIZE`, `TASK_COLUMNS`, `TaskRow`,
  `ARCHIVE_AFTER_DAYS`, типы `Task`, `TaskFeatures`, `TaskListParams`, `TaskListRequest`,
  `TaskStatus`, `TaskPriority`
