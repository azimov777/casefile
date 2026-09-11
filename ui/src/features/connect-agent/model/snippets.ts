/**
 * Фрагменты подключения агента к MCP: тексты, которые человек копирует в свой клиент.
 *
 * Собирает их одна функция из трёх входов — адреса, токена и признака «нужна метка» — и
 * больше нигде текст фрагмента не набирается: экран «Подключить агента» зовёт её без
 * токена, экран «Доступы» (UI-106) — с только что выпущенным секретом, и расходиться им
 * негде (`UI-105#13`).
 *
 * Ключи чужих клиентов здесь не придуманы: каждый сверен по документации клиента и его
 * справке (`UI-105#14`). Подписей на языке человека во фрагментах нет — это код клиента,
 * и он одинаков на любом языке интерфейса; объяснения к фрагментам живут в словаре.
 */

/** Имя сервера в конфигурации клиента — то же, что в README и выводе установщика. */
export const SERVER_NAME = 'casefile';

/**
 * Переменная окружения, из которой Codex берёт токен (`bearer_token_env_var`). Путь
 * через переменную выбран потому, что секрет не ложится в файл конфигурации.
 */
export const TOKEN_ENV = 'CASEFILE_TOKEN';

/** Файл конфигурации Codex, в который ложится секция `[mcp_servers.<имя>]`. */
export const CODEX_CONFIG_PATH = '~/.codex/config.toml';

/** Заголовок, которым общий агентский токен называет временного агента. */
export const LABEL_HEADER = 'X-Actor-Label';

/**
 * Подстановки на месте значений, которых у экрана нет. Угловые скобки выбраны
 * намеренно: забытая подстановка не сойдёт за значение — бэкенд отклонит и такой
 * токен, и такую метку, а не примет молча.
 */
export const TOKEN_PLACEHOLDER = '<token>';
export const LABEL_PLACEHOLDER = '<label>';

export interface SnippetInput {
  /** Адрес MCP из `GET /api/v1/installation` → `mcp_url`, целиком и как есть. */
  mcpUrl: string;
  /** Секрет токена. Нет — на его месте стоит `TOKEN_PLACEHOLDER`. */
  token?: string;
  /**
   * Токен общий агентский — выпущен без участника: каждый запрос с ним обязан нести
   * `X-Actor-Label` (`../docs/CONCEPT.md`, 3.1), иначе бэкенд отвечает
   * `actor_label_required`.
   */
  labelled: boolean;
}

/** Поле формы подключения в приложении Codex и ключ файла, на который оно ложится. */
export interface CodexFormField {
  key: 'url' | 'bearer_token_env_var' | 'http_headers';
  /** Для заголовков — имя заголовка, для остальных полей — `null`. */
  name: string | null;
  value: string;
}

export interface SnippetTexts {
  /** Любой клиент MCP: заголовки, которые идут с каждым запросом, по строке на заголовок. */
  headers: string;
  /** Команда Claude Code одной строкой: так она вставляется в любую оболочку. */
  claudeCode: string;
  /** Секция `~/.codex/config.toml`. */
  codexFile: string;
  /** Переменная окружения с токеном для Codex. */
  codexEnv: string;
  /** Те же значения полями формы приложения Codex. */
  codexForm: CodexFormField[];
  /** Конфигурация `mcpServers` в форме `.mcp.json` Claude Code. */
  json: string;
}

export function connectionSnippets({ mcpUrl, token, labelled }: SnippetInput): SnippetTexts {
  const secret = token ?? TOKEN_PLACEHOLDER;
  const authorization = `Bearer ${secret}`;

  // Заголовки одним списком на все фрагменты: метка не может оказаться в одном и
  // пропасть в соседнем.
  const headers: [string, string][] = [['Authorization', authorization]];
  if (labelled) headers.push([LABEL_HEADER, LABEL_PLACEHOLDER]);

  return {
    headers: headers.map(([name, value]) => `${name}: ${value}`).join('\n'),
    claudeCode: claudeCodeCommand(mcpUrl, headers),
    codexFile: codexFile(mcpUrl, labelled),
    codexEnv: `export ${TOKEN_ENV}=${shellQuote(secret)}`,
    codexForm: [
      { key: 'url', name: null, value: mcpUrl },
      { key: 'bearer_token_env_var', name: null, value: TOKEN_ENV },
      ...(labelled
        ? [{ key: 'http_headers' as const, name: LABEL_HEADER, value: LABEL_PLACEHOLDER }]
        : []),
    ],
    json: JSON.stringify(
      {
        mcpServers: {
          [SERVER_NAME]: { type: 'http', url: mcpUrl, headers: Object.fromEntries(headers) },
        },
      },
      null,
      2,
    ),
  };
}

/**
 * `claude mcp add` с заголовками **после** имени и адреса. У флага `--header` значение
 * вариадическое (`-H, --header <header...>` в справке): поставленный раньше
 * позиционных аргументов, он забрал бы в заголовки и имя сервера, и адрес.
 */
function claudeCodeCommand(mcpUrl: string, headers: [string, string][]): string {
  const flags = headers.map(([name, value]) => `--header ${shellQuote(`${name}: ${value}`)}`);
  return [
    'claude mcp add --transport http --scope user',
    SERVER_NAME,
    shellQuote(mcpUrl),
    ...flags,
  ].join(' ');
}

/**
 * Секция Codex. Токен в файл не пишется вовсе — только имя переменной, из которой его
 * возьмёт Codex: ключа для токена строкой у Codex в документации нет, и это к лучшему.
 * Метка — постоянное значение и потому ложится в `http_headers`, а не в
 * `env_http_headers`.
 */
function codexFile(mcpUrl: string, labelled: boolean): string {
  const lines = [
    `[mcp_servers.${SERVER_NAME}]`,
    `url = ${tomlString(mcpUrl)}`,
    `bearer_token_env_var = ${tomlString(TOKEN_ENV)}`,
  ];
  if (labelled) {
    lines.push(`http_headers = { ${tomlString(LABEL_HEADER)} = ${tomlString(LABEL_PLACEHOLDER)} }`);
  }
  return lines.join('\n');
}

/**
 * Строка TOML в двойных кавычках. Экранирование строки JSON годится и для TOML: у
 * базовой строки TOML те же `\"`, `\\`, `\n` и `\uXXXX`.
 */
function tomlString(value: string): string {
  return JSON.stringify(value);
}

/**
 * Значение в двойных кавычках для оболочки. Внутри них `sh`, `bash` и `zsh` ещё
 * раскрывают `$`, обратную кавычку и `\`, поэтому эти знаки экранируются, как и сама
 * кавычка: адрес задаёт установка, и знак, случайно ставший командой, дорого стоит.
 */
export function shellQuote(value: string): string {
  return `"${value.replace(/["\\$`]/g, '\\$&')}"`;
}
