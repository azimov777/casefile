/** Экран дела: лента записей и отбор по типам (`src/pages/case`). */
export const caseScreen = {
  /** Пояснение экрана (`features/manage-onboarding`, `ExplanationPanel`, `TRK-363`). */
  explanation: {
    body: 'Дело — журнал задачи: решения, попытки, находки, вопросы и ответы. Записи не правятся и не удаляются; ошибку исправляет следующая запись. По делу следующий агент продолжает работу, не начиная заново.',
  },
  missingTitle: 'Дела {{key}} нет',
  missingText: 'Задачи с таким ключом нет, а значит нет и дела.',
  backToList: 'Вернуться к списку задач',
  title: 'Дело {{key}}',
  toLatest: 'К свежей записи',
  loading: 'Читаем дело…',
  emptyByTypes: 'По этим типам записей в деле нет.',
  noAnswerYet: 'Ответа пока нет.',
  noResolutionYet: 'Разбора пока нет.',
  more: 'Ещё',
  loadingMore: 'Читаем…',
  fromStart: 'Читать дело сначала',

  window: {
    shown: 'Показаны записи после {{reference}}.',
    hiddenByType: 'Записи {{reference}} не видно: она не попадает в отбор по типу.',
    showAllTypes: 'Показать все типы',
    missing:
      'Записи {{reference}} в деле нет: возможно, номер набран с опечаткой или ссылка ведёт в другую задачу.',
  },

  end_one: 'Это всё дело, в нём {{count, number}} запись.',
  end_few: 'Это всё дело, в нём {{count, number}} записи.',
  end_many: 'Это всё дело, в нём {{count, number}} записей.',
  end_other: 'Это всё дело, в нём {{count, number}} записи.',
  endOfWindow_one: 'Это конец дела, показана {{count, number}} запись.',
  endOfWindow_few: 'Это конец дела, показано {{count, number}} записи.',
  endOfWindow_many: 'Это конец дела, показано {{count, number}} записей.',
  endOfWindow_other: 'Это конец дела, показано {{count, number}} записи.',

  filters: {
    label: 'Отбор записей',
    menu: 'Фильтр',
    menuLabel: 'Типы записей',
    agentEntries: 'Записи агента',
    serviceEntries: 'Служебные',
    chosen: 'Отобранные типы записей',
    allShown: 'показаны все записи',
    remove: 'Убрать тип: {{type}}',
    reset: 'Сбросить',
  },
} as const;
