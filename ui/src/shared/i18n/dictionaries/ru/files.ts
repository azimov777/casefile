/**
 * Экран «Файлы» (TRK-739, слово владельца TRK~8#4): все файлы установки одним списком.
 * Поиск по имени, сортировка, отбор по типу и проекту; открыть, загрузить, заменить и
 * удалить — один файл, выбранные или всё, что отобрал фильтр.
 */
export const files = {
  /** Пояснение экрана (`features/manage-onboarding`, `ExplanationPanel`). */
  explanation: {
    body: 'Все файлы установки в одном месте: то, что люди и агенты приложили к записям или загрузили сюда. Файл принадлежит одному проекту и при замене сохраняет свою ссылку. Удаление стирает байты и оставляет только след: имя, тип и кто удалил.',
  },
  intro:
    'Файлы всех проектов одним списком. Найдите файл по имени, отсортируйте список, сузьте его по типу или проекту. Удаление стирает байты насовсем; в записях, которые прикладывали файл, остаётся след.',
  loading: 'Читаю файлы…',
  empty: 'В этой установке файлов пока нет. Загрузите файл здесь, или агент приложит его к записи.',
  emptyFiltered: 'Под поиск и фильтры не подошёл ни один файл.',
  close: 'Закрыть',
  cancel: 'Отмена',

  list: {
    label: 'Файлы',
    shown_one: 'Показан {{count, number}} файл',
    shown_few: 'Показано {{count, number}} файла',
    shown_many: 'Показано {{count, number}} файлов',
    shown_other: 'Показано {{count, number}} файла',
    unopenedCount_one: 'Давно не открывали: {{count, number}} изображение',
    unopenedCount_few: 'Давно не открывали: {{count, number}} изображения',
    unopenedCount_many: 'Давно не открывали: {{count, number}} изображений',
    unopenedCount_other: 'Давно не открывали: {{count, number}} изображения',
    moreAvailable: 'есть ещё',
    more: 'Показать ещё',
    loadingMore: 'Читаю…',
  },

  units: { bytes: 'Б', kilobytes: 'КБ', megabytes: 'МБ', gigabytes: 'ГБ' },

  filters: {
    label: 'Поиск и фильтры',
    search: 'Поиск по имени',
    searchPlaceholder: 'Часть имени файла',
    project: 'Проект',
    allProjects: 'Все проекты',
    type: 'Тип',
    sort: 'Сортировать по',
    descending: 'По убыванию',
    ascending: 'По возрастанию',
    direction: 'Порядок: {{current}}',
    unopened: 'Давно не открывали',
    unopenedTerm_one: 'Изображения, которые не открывали {{count, number}} день. Срок —',
    unopenedTerm_few: 'Изображения, которые не открывали {{count, number}} дня. Срок —',
    unopenedTerm_many: 'Изображения, которые не открывали {{count, number}} дней. Срок —',
    unopenedTerm_other: 'Изображения, которые не открывали {{count, number}} дня. Срок —',
    unopenedSettings: 'настройка установки, меняется в «Настройках»',
    reset: 'Сбросить',
    types: {
      all: 'Все типы',
      image: 'Изображения',
      pdf: 'PDF',
      word: 'Документы Word',
      excel: 'Таблицы Excel',
      text: 'Текст',
      audio: 'Звук',
      video: 'Видео',
    },
    sorts: {
      added: 'Дате добавления',
      opened: 'Последнему открытию',
      size: 'Размеру',
      type: 'Типу',
    },
  },

  item: {
    label: 'Файл {{name}}',
    select: 'Выбрать {{name}}',
    project: 'Проект {{key}}',
    addedBy: 'Добавил {{author}}',
    addedByTracker: 'Добавил трекер',
    opened: 'Последний раз открыт',
    unopened: 'Давно не открывали',
    neverOpened: 'Не открывали',
    replaced: 'Заменил {{author}}',
    replacedByTracker: 'Заменил трекер',
    refs_one: 'Приложен к {{count, number}} записи, задач: {{tasks, number}}',
    refs_few: 'Приложен к {{count, number}} записям, задач: {{tasks, number}}',
    refs_many: 'Приложен к {{count, number}} записям, задач: {{tasks, number}}',
    refs_other: 'Приложен к {{count, number}} записи, задач: {{tasks, number}}',
    noRefs: 'Ни к одной записи не приложен',
    archived: 'Проект в архиве: файл можно открыть, но не менять',
  },

  actions: {
    open: 'Открыть',
    download: 'Скачать',
    replace: 'Заменить',
    delete: 'Удалить',
  },

  preview: {
    title: '{{name}}',
    intro:
      'Файл открывается из установки, и это считается его последним открытием. Здесь показываются только изображения — остальное скачайте.',
    loading: 'Читаю файл…',
    notImage: 'Файл такого вида здесь не показывается. Скачайте его.',
    alt: 'Изображение {{name}}',
  },

  upload: {
    open: 'Загрузить файл',
    title: 'Загрузить файл',
    intro: 'Файл кладётся в один проект и остаётся в нём до удаления.',
    project: 'Проект',
    projectPlaceholder: 'Выберите проект',
    noProjects: 'Некуда положить файл: проектов нет. Сначала заведите проект.',
    file: 'Файл',
    name: 'Имя',
    nameHint: 'Оставьте пустым, и файл сохранит имя, которое у него на вашем компьютере.',
    submit: 'Загрузить',
    pending: 'Загружаю…',
  },

  replace: {
    title: 'Заменить {{name}}',
    intro:
      'Новые байты ложатся под ту же ссылку: каждая запись, прикладывавшая файл, покажет новое содержимое. Прежнее содержимое стирается, истории версий нет.',
    file: 'Новый файл',
    name: 'Новое имя',
    nameHint: 'Оставьте пустым, и имя останется прежним.',
    submit: 'Заменить',
    pending: 'Заменяю…',
  },

  remove: {
    singleTitle: 'Удалить {{name}}?',
    singleIntro:
      'Байты стираются насовсем, остаётся след: имя, тип, размер и кто удалил. Записи, прикладывавшие файл, покажут, что он удалён.',
    manyTitle_one: 'Удалить {{count, number}} файл?',
    manyTitle_few: 'Удалить {{count, number}} файла?',
    manyTitle_many: 'Удалить {{count, number}} файлов?',
    manyTitle_other: 'Удалить {{count, number}} файла?',
    matchingTitle_one: 'Удалить {{count, number}} файл, отобранный фильтром?',
    matchingTitle_few: 'Удалить все {{count, number}} файла, отобранные фильтром?',
    matchingTitle_many: 'Удалить все {{count, number}} файлов, отобранные фильтром?',
    matchingTitle_other: 'Удалить все {{count, number}} файла, отобранные фильтром?',
    manyIntro:
      'Байты каждого файла ниже стираются насовсем, от каждого остаётся след: имя, тип, размер и кто удалил. Записи, прикладывавшие файл, покажут, что он удалён.',
    refs_one: 'Приложены к {{count, number}} записи (сумма по файлам; задач: {{tasks, number}})',
    refs_few: 'Приложены к {{count, number}} записям (сумма по файлам; задач: {{tasks, number}})',
    refs_many: 'Приложены к {{count, number}} записям (сумма по файлам; задач: {{tasks, number}})',
    refs_other: 'Приложены к {{count, number}} записи (сумма по файлам; задач: {{tasks, number}})',
    noRefs: 'Ни один из них не приложен к записи.',
    counting: 'Считаю файлы, которые отобрал фильтр…',
    countFailed: 'Не удалось посчитать файлы. Попробуйте ещё раз.',
    countAgain: 'Посчитать ещё раз',
    confirmCount: 'Удаляю ровно {{count, number}}',
    confirm: 'Удалить',
    pending: 'Удаляю…',
    done_one: 'Удалён {{count, number}} файл.',
    done_few: 'Удалено {{count, number}} файла.',
    done_many: 'Удалено {{count, number}} файлов.',
    done_other: 'Удалено {{count, number}} файла.',
    mismatch:
      'Пока окно было открыто, число подходящих файлов стало {{actual, number}}: ничего не удалено. Проверьте новое число и подтвердите снова.',
    moreFiles_one: 'и ещё {{count, number}} файл',
    moreFiles_few: 'и ещё {{count, number}} файла',
    moreFiles_many: 'и ещё {{count, number}} файлов',
    moreFiles_other: 'и ещё {{count, number}} файла',
  },

  selection: {
    selected_one: 'Выбран {{count, number}} файл',
    selected_few: 'Выбрано {{count, number}} файла',
    selected_many: 'Выбрано {{count, number}} файлов',
    selected_other: 'Выбрано {{count, number}} файла',
    selectAll: 'Выбрать все показанные',
    clear: 'Снять выбор',
    deleteSelected: 'Удалить выбранные',
    deleteMatching: 'Удалить все отобранные',
    deleteUnopened: 'Удалить все давно не открытые',
    deleteEverything: 'Удалить все файлы',
  },

  attach: {
    label: 'Файлы',
    pick: 'Прикрепить файл',
    input: 'Выбрать файлы для записи',
    uploading: 'Загружаю…',
    remove: 'Убрать {{name}} из записи',
    removeShort: 'Убрать',
    full: 'Больше {{max}} файлов к записи не приложить.',
  },

  entryFiles: {
    label: 'Файлы записи',
    hide: 'Скрыть',
    deleted: 'Файл удалён',
    deletedBy: 'Удалил {{author}}',
    deletedByTracker: 'Удалил трекер',
  },
};
