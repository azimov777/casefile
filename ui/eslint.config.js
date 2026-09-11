import js from '@eslint/js';
import prettier from 'eslint-config-prettier';
import i18next from 'eslint-plugin-i18next';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  // Сгенерированный клиент не наш код: его форма — свойство контракта.
  {
    ignores: [
      'dist',
      'node_modules',
      'playwright-report',
      'test-results',
      'src/shared/api/openapi.ts',
    ],
  },
  js.configs.recommended,
  tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser, ...globals.node },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      '@typescript-eslint/consistent-type-imports': ['error', { prefer: 'type-imports' }],
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
    },
  },
  {
    // Тестовая обвязка не участвует в горячей перезагрузке: правило про экспорт
    // только компонентов из файла здесь ни о чём.
    files: ['testing/**/*.tsx'],
    rules: { 'react-refresh/only-export-components': 'off' },
  },
  {
    /*
     * Сторож подписей: в разметке не набирают текст руками (UI-80).
     *
     * Ловится не язык, а место. Английская подпись мимо словаря выглядит как обычная
     * строка, и грепом она не отличается от `className`, — поэтому сторож разбирает
     * дерево кода: литерал в тексте разметки и в атрибуте, которым говорят с человеком,
     * это нарушение, а тот же литерал в `className`, `tone` или `to` — нет.
     *
     * Правится код, а не этот список: подпись переезжает в словарь
     * (`shared/i18n/dictionaries`) и приходит на экран через `useTranslation`.
     */
    files: ['src/**/*.tsx'],
    plugins: { i18next },
    rules: {
      'i18next/no-literal-string': [
        'error',
        {
          // Кроме текста разметки проверяются выражения внутри названных ниже атрибутов:
          // `aria-label={ok ? 'Да' : 'Нет'}` — такая же подпись, как и текст.
          mode: 'jsx-only',
          /*
           * Непустой `include` делает список атрибутов белым: проверяются только
           * названные, а остальные пропускаются вместе со своими выражениями.
           * Со списком по умолчанию (чёрным) сторож давал 80 ложных срабатываний на
           * нынешнем коде — `tone="danger"`, `to="/tasks"`, `navigate('/tasks')`
           * внутри `onClick`, — и подгонять под них код запрещено.
           *
           * Здесь перечислено всё, чем разметка говорит с человеком помимо текста:
           * подпись для программы чтения с экрана, подсказка, подсказка поля ввода
           * и замена картинке.
           */
          'jsx-attributes': {
            include: ['aria-label', 'aria-description', 'title', 'placeholder', 'alt'],
          },
          /*
           * Взятие подписи из словаря подписью не является. Список перебивает
           * умолчания правила целиком (`{...defaults, ...options}` в его `create`),
           * поэтому умолчания переписаны сюда, а наших имён в нём два: `brick` — тот же
           * `t`, переименованный при разборе (`const { t: brick } = useTranslation('ui')`),
           * `say.*` — помощник страничных тестов (`testing/say.ts`).
           */
          callees: {
            exclude: [
              'i18n(ext)?',
              't',
              'brick',
              'say\\.\\w+',
              'require',
              'addEventListener',
              'removeEventListener',
              'postMessage',
              'getElementById',
              'dispatch',
              'commit',
              'includes',
              'indexOf',
              'endsWith',
              'startsWith',
            ],
          },
          message:
            'Подпись набрана прямо в разметке. Её место — словарь `shared/i18n/dictionaries`, а на экран она приходит через `useTranslation`',
        },
      ],
    },
  },
  {
    /*
     * Тот же сторож за пределами разметки (UI-80).
     *
     * Подпись живёт не только в JSX: «только что» пряталось в `shared/lib/time.ts`,
     * и проверка по одним лишь `*.tsx` его не увидела (UI-79#8). Здесь ловится русская
     * строка в коде приложения — и заодно язык, набранный литералом: написанный по
     * привычке `new Intl.NumberFormat('ru-RU')` вернул бы прошитую локаль, от которой
     * уходила вся программа UI-76, и не уронил бы ничего.
     *
     * Комментарии узлами дерева не являются и под отбор не попадают ни в каком виде:
     * русский остаётся языком разработки.
     */
    files: ['src/**/*.{ts,tsx}'],
    ignores: [
      // Модуль, в котором язык и живёт: словари, названия языков на них самих
      // (`English` и `Русский` не переводятся никогда) и имена языков в путях.
      'src/shared/i18n/**',
      // Тест называет себя по-русски и сверяет русские фразы, вписанные руками, —
      // это тот же язык разработки, что и комментарий.
      'src/**/*.test.{ts,tsx}',
    ],
    rules: {
      'no-restricted-syntax': [
        'error',
        /*
         * Единственное исключение записано отбором по месту, а не списком файлов:
         * строка журнала разработчика (`new Error(...)`, `console.warn(...)`) человеку
         * не показывается — текст отказа ему собирает `shared/errors` по `error.code`,
         * а `message` был технической фразой для журнала и остаётся ею (UI-76).
         * Файловый список освобождал бы весь файл целиком и дописывался бы при каждом
         * новом отказе.
         */
        {
          selector:
            "Literal[value=/[А-Яа-яЁё]/]:not(NewExpression[callee.name=/Error$/] *):not(CallExpression[callee.object.name='console'] *)",
          message:
            'Русская строка в коде приложения. Подпись человеку живёт в словарях `shared/i18n/dictionaries`; фраза для журнала разработчика законна только внутри `new Error(...)` или `console.*`',
        },
        {
          selector:
            "TemplateElement[value.raw=/[А-Яа-яЁё]/]:not(NewExpression[callee.name=/Error$/] *):not(CallExpression[callee.object.name='console'] *)",
          message:
            'Русская строка в коде приложения. Подпись человеку живёт в словарях `shared/i18n/dictionaries`; фраза для журнала разработчика законна только внутри `new Error(...)` или `console.*`',
        },
        {
          selector: 'Literal[value=/^(ru|en)(-[A-Z]{2})?$/]',
          message:
            'Язык набран литералом. Он приходит из `shared/i18n` — `useLanguage()` в компоненте, `DEFAULT_LANGUAGE` в умолчании: прошитая локаль это то, от чего уходила программа UI-76',
        },
      ],
    },
  },
  prettier,
);
