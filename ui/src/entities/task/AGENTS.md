# src/entities/task

Задача: типы из контракта, запрос списка и представление одной строки. Признаки
(`blocked`, счётчики вопросов, время последней сводки) приезжают в самой строке выдачи,
поэтому запроса на задачу отсюда нет.

## Папки

- `api/` — `tasks.ts`: параметры отбора, запросы списка, столбца доски и числа выдачи,
  ключи запросов, наборы значений
- `ui/` — строка таблицы и заголовки её столбцов

## Файлы

- `index.ts` — публичный интерфейс среза: `tasksQueryOptions`, `tasksColumnQueryOptions`,
  `tasksTotalQueryOptions`, `fetchTasks`, `taskKeys`, `TASK_STATUSES`, `TASK_PRIORITIES`,
  `TASK_LIST_FIELDS`, `TASK_PAGE_SIZE`, `TASK_COLUMN_PAGE_SIZE`, `TASK_COLUMNS`, `TaskRow`,
  типы `Task`, `TaskFeatures`, `TaskListParams`, `TaskStatus`, `TaskPriority`
