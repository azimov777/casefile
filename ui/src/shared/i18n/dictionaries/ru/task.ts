/** Экран карточки задачи: шапка, блоки задания и опись дела (`src/pages/task`). */
export const task = {
  missingTitle: 'Задачи {{key}} нет',
  missingText:
    'Задачи с таким ключом нет: возможно, ключ набран с опечаткой или задача из другой установки.',
  backToList: 'Вернуться к списку задач',
  loading: 'Загружаем задачу {{key}}…',

  summary: 'Последняя сводка',
  noSummary: 'Сводки ещё нет: по этой задаче никто не отчитывался.',
  questions: 'Открытые вопросы',
  noQuestions: 'Вопросов без ответа нет.',
  remarks: 'Замечания',
  noRemarks: 'Неразобранных замечаний нет.',
  case: 'Дело',
  openCase: 'Открыть всё дело лентой',
  assignment: 'Задание',
  links: 'Связи',
  noLinks: 'Связей нет.',

  header: {
    assignee: 'исполнитель',
    unassigned: 'не назначен',
    updated: 'Обновлена',
    created: 'Заведена',
    transitions: 'Возможные переходы',
    transitionsTitle:
      'Куда задача может уйти по таблице статусов. Проверки перехода считаются в момент перехода',
    noTransitions: 'никуда: статус конечный',
  },

  sections: {
    description: 'Описание',
    goal: 'Цель',
    context: 'Контекст',
    constraints: 'Ограничения',
    output: 'Выход',
    checks: 'Обзорные проверки',
    noChecks: 'Проверок нет.',
    empty: 'Раздел пуст.',
  },

  index: {
    empty: 'Дело пусто: записей ещё нет.',
    toLatest: 'К свежей записи',
    toTop: 'В начало описи',
    count_one: 'В деле {{count, number}} запись',
    count_few: 'В деле {{count, number}} записи',
    count_many: 'В деле {{count, number}} записей',
    count_other: 'В деле {{count, number}} записи',
    loadingEntry: 'Читаем запись…',
    columns: {
      no: '№',
      type: 'Тип',
      author: 'Автор',
      when: 'Когда',
      headline: 'Заголовок',
    },
  },
} as const;
