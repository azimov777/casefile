/**
 * Ключи пояснений экранов одним местом в коде (TRK-362): следующая задача (TRK-363)
 * дописывает сюда остальные экраны, ничего не меняя в компоненте пояснения.
 *
 * Ключ — непрозрачная строка по шаблону бэкенда (`OnboardingHintsUpdate.hidden`,
 * `^[a-z][a-z0-9_.-]{0,63}$`): сервер не знает экранов интерфейса, поэтому шаблон
 * не проверяется здесь ни разу — типы контракта его и так не пускают на сервер иначе.
 */
export const HINT_KEYS = {
  /** Входящая (`pages/questions`): что здесь и что делает человек (TRK-362). */
  questions: 'questions',
  /** Список задач, вид «таблица» (`pages/tasks`, TRK-363). */
  tasks: 'tasks',
  /** Список задач, вид «доска»: свой ключ, закрытое на списке доску не закрывает (TRK-363). */
  board: 'board',
  /** Карточка задачи (`pages/task`, TRK-363). */
  task: 'task',
  /** Дело задачи (`pages/case`, TRK-363). */
  case: 'case',
  /** Проект (`pages/project`, TRK-363). */
  project: 'project',
  /** Подключить агента (`pages/connect`, TRK-363). */
  connect: 'connect',
  /** Доступы (`pages/access`, TRK-363). */
  access: 'access',
} as const;

export type HintKey = (typeof HINT_KEYS)[keyof typeof HINT_KEYS];
