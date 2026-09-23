/**
 * Экран списка задач: таблица, доска и отбор над ними (`src/pages/tasks`,
 * `src/features/task-filters`).
 */
export const tasks = {
  title: 'Задачи',
  loading: 'Загружаем задачи…',
  found_zero: 'Ничего не нашлось',
  found_one: 'Нашлась {{count, number}} задача',
  found_few: 'Нашлось {{count, number}} задачи',
  found_many: 'Нашлось {{count, number}} задач',
  found_other: 'Нашлось {{count, number}} задачи',
  empty: 'Задач по этим условиям нет',
  archiveHidden: 'Архив не показан.',
  showArchive: 'Показать архив',
  resetFilters: 'Сбросить фильтры',
  beyond_one:
    'На этой странице задач нет: по этим условиям есть {{count, number}} задача, и она на предыдущих страницах',
  beyond_few:
    'На этой странице задач нет: по этим условиям есть {{count, number}} задачи, и все они на предыдущих страницах',
  beyond_many:
    'На этой странице задач нет: по этим условиям есть {{count, number}} задач, и все они на предыдущих страницах',
  beyond_other:
    'На этой странице задач нет: по этим условиям есть {{count, number}} задачи, и все они на предыдущих страницах',

  table: {
    caption_one: 'На этой странице {{count, number}} задача',
    caption_few: 'На этой странице {{count, number}} задачи',
    caption_many: 'На этой странице {{count, number}} задач',
    caption_other: 'На этой странице {{count, number}} задачи',
  },

  paging: {
    label: 'Страницы выдачи',
    previous: 'Предыдущая страница',
    next: 'Следующая страница',
    page: 'Страница {{page}}',
    pageOf: 'Страница {{page}} из {{pages, number}}',
    total_one: '{{count, number}} страница',
    total_few: '{{count, number}} страницы',
    total_many: '{{count, number}} страниц',
    total_other: '{{count, number}} страницы',
  },

  board: {
    reading: 'Читаем задачи столбца…',
    readingMore: 'Читаем ещё…',
    // «сколько-то из ?»: числа выдачи бэкенд не назвал, и точным его не заменить.
    ofUnknown: '{{count, number}} из ?',
    // Свёрнутый столбец не читал ничего: без числа от бэкенда сказать ему нечего.
    unknown: '?',
    empty: 'Пусто',
  },

  view: {
    label: 'Вид списка',
    table: 'Таблица',
    board: 'Доска',
  },

  filters: {
    label: 'Отбор задач',
    conditions: 'Условия отбора',
    allShown: 'показаны все задачи',
    allButArchive: 'показаны все задачи, кроме архива',
    remove: 'Убрать условие: {{condition}}',
    reset: 'Сбросить',
    menu: 'Фильтр',
    menuLabel: 'Условия отбора задач',
    statusLegend: 'Статус',
    priorityLegend: 'Приоритет',
    flagsLegend: 'Признаки',
    assignee: 'Исполнитель',
    assigneePlaceholder: 'имя целиком',
    text: 'Текст',
    textPlaceholder: 'Найти в названии или описании',
    blocked: 'заблокирована',
    withQuestions: 'есть открытые вопросы',
    withRemarks: 'есть неразобранные замечания',
    pending: 'не применено, Enter применит',
    pendingShort: '↵ применить',
    apply: 'Применить',

    archive: {
      label: 'показывать архив',
      // «больше N дня» — родительный падеж: одного дня, но двух, пяти дней.
      hint_one: 'Архив — закрытые задачи, в деле которых больше {{count, number}} дня нет записей',
      hint_few: 'Архив — закрытые задачи, в деле которых больше {{count, number}} дней нет записей',
      hint_many:
        'Архив — закрытые задачи, в деле которых больше {{count, number}} дней нет записей',
      hint_other:
        'Архив — закрытые задачи, в деле которых больше {{count, number}} дня нет записей',
    },

    sort: {
      label: 'Сортировка',
      '-last_entry_at': 'сначала живые в деле',
      last_entry_at: 'сначала затихшие',
      '-updated_at': 'сначала недавно правленные',
      updated_at: 'сначала давно не тронутые',
      '-priority': 'сначала важные',
      priority: 'сначала неважные',
      key: 'по ключу',
      '-key': 'по ключу, с конца',
    },

    query: {
      toggle: 'Запрос',
      label: 'Запрос на языке бэкенда',
      note: 'Запрос заменяет простой отбор; архив по-прежнему решает флажок справа.',
      placeholder: 'queue: DEMO and status: open and blocked: false',
      errorAt: 'Ошибка в символе {{position}}.',
      allowed: 'Допустимо: {{list}}',
      stale: 'Показаны строки предыдущего отбора.',
    },

    condition: {
      query: 'запрос: {{query}}',
      status: 'статус {{values}}',
      priority: 'приоритет {{values}}',
      assignee: 'исполнитель {{value}}',
      text: 'текст «{{value}}»',
      blocked: 'только заблокированные',
      questions: 'есть открытые вопросы',
      remarks: 'есть неразобранные замечания',
    },
  },
} as const;
