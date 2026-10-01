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

/**
 * Адрес, который у Codex уже прописан в плагине (`.codex-plugin/mcp.json`): другой адрес
 * ему задаёт строка в `config.toml` (TRK-451#13, TRK-452#18).
 */
const CODEX_PLUGIN_URL = 'http://127.0.0.1:8100/mcp';

/**
 * Установка скила для клиентов без плагина — `npx skills` и строка на машину агента
 * (TRK-420, `TRK-401#18`). Команды те же, что печатают `install.sh` и
 * `docs/agent-install.md`; `snippets.test.ts` сверяет их с гайдом. Скил общий для всех
 * установок, поэтому ни адреса, ни токена в этих текстах нет. Claude Code и Codex
 * получают скил вместе с подключением — плагином (`claudePlugin`, `codexPlugin`).
 */
const SKILL_REPO = 'azimov777/casefile';
const SKILL_CHANNEL = 'stable';
/**
 * Ветка маркетплейса Claude Code и Codex: в ней одни файлы плагина (TRK-494). Со `stable`
 * харнесс уносил к себе и файлы корня репозитория, `--sparse` их не отсекает.
 */
const PLUGIN_BRANCH = 'plugin';
const SKILL_INSTALLER = `https://raw.githubusercontent.com/${SKILL_REPO}/main`;

/** Поле пункта «Добавить маркетплейс» приложения Codex (`TRK-397#22`). */
export interface CodexMarketplaceField {
  key: 'source' | 'ref';
  value: string;
}

export interface SkillTexts {
  /** Любой другой агент. */
  other: string;
  /**
   * Одна строка на машине агента, без Docker: ставит скил во все найденные там харнессы
   * и, с адресом установки в `CASEFILE_URL`, плагин Claude Code и Codex (`install.sh`,
   * TRK-452#18, `docs/agent-install.md`). Оболочек две, как у переменной Codex, и по той
   * же причине (`UI-114#5`).
   */
  machine: { bashZsh: string; powerShell: string };
}

/** Адрес из безопасных знаков остаётся как есть, как в гайде; прочий берётся в одинарные кавычки. */
function bashWord(value: string): string {
  return /^[A-Za-z0-9:/._~?&=%@+,-]+$/.test(value) ? value : `'${value.replace(/'/g, `'\\''`)}'`;
}

function skillTexts(mcpUrl: string): SkillTexts {
  return {
    other: `npx skills add ${SKILL_REPO}#${SKILL_CHANNEL}`,
    machine: {
      bashZsh: `curl -fsSL ${SKILL_INSTALLER}/install.sh | CASEFILE_SKILL_ONLY=1 CASEFILE_URL=${bashWord(mcpUrl)} sh`,
      powerShell: `$env:CASEFILE_SKILL_ONLY=1; $env:CASEFILE_URL='${mcpUrl.replace(/'/g, "''")}'; irm ${SKILL_INSTALLER}/install.ps1 | iex`,
    },
  };
}

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

export interface SnippetTexts {
  /** Любой клиент MCP без OAuth: заголовки, которые идут с каждым запросом, по строке на заголовок. */
  headers: string;
  /**
   * Claude Code: маркетплейс, плагин с адресом установки и вход OAuth, по строке на
   * команду. Ключа нет нигде: плагин несёт и скил, и подключение (TRK-452#18).
   */
  claudePlugin: string;
  /** Codex: маркетплейс со всеми тремя путями, плагин и вход OAuth. Ключа нет. */
  codexPlugin: string;
  /** Те же значения полями пункта «Добавить маркетплейс» приложения Codex. */
  codexMarketplace: CodexMarketplaceField[];
  /**
   * Строки `config.toml` с адресом установки, если он не тот, что зашит в плагин Codex;
   * иначе `null`. Токена в них нет — вход OAuth.
   */
  codexUrlFile: string | null;
  /**
   * Служба отдаёт вход OAuth только по https, а по http — лишь на своей машине
   * (`install.sh`, TRK-451#13). Вне этого плагин подключиться не сможет.
   */
  oauthAvailable: boolean;
  /** Конфигурация `mcpServers` в форме `.mcp.json` — для клиентов без OAuth, с ключом. */
  json: string;
  /** Установка скила для клиентов без плагина; зависит только от адреса (`CASEFILE_URL`). */
  skill: SkillTexts;
}

export function connectionSnippets({ mcpUrl, token, labelled }: SnippetInput): SnippetTexts {
  const secret = token ?? TOKEN_PLACEHOLDER;
  const authorization = `Bearer ${secret}`;

  // Заголовки одним списком на все фрагменты с ключом: метка не может оказаться в одном и
  // пропасть в соседнем.
  const headers: [string, string][] = [['Authorization', authorization]];
  if (labelled) headers.push([LABEL_HEADER, LABEL_PLACEHOLDER]);

  return {
    headers: headers.map(([name, value]) => `${name}: ${value}`).join('\n'),
    claudePlugin: [
      `claude plugin marketplace add ${SKILL_REPO}#${PLUGIN_BRANCH}`,
      `claude plugin install casefile@casefile --scope user --config ${shellQuote(`casefile_url=${mcpUrl}`)}`,
      `claude mcp login ${CLAUDE_LOGIN_SERVER}`,
    ].join('\n'),
    codexPlugin: [
      `codex plugin marketplace add ${SKILL_REPO} --ref ${PLUGIN_BRANCH}`,
      'codex plugin add casefile@casefile',
      `codex mcp login ${SERVER_NAME}`,
    ].join('\n'),
    codexMarketplace: [
      { key: 'source', value: SKILL_REPO },
      { key: 'ref', value: PLUGIN_BRANCH },
    ],
    codexUrlFile:
      normalizeUrl(mcpUrl) === normalizeUrl(CODEX_PLUGIN_URL)
        ? null
        : [`[mcp_servers.${SERVER_NAME}]`, `url = ${tomlString(mcpUrl)}`].join('\n'),
    oauthAvailable: isOAuthAddress(mcpUrl),
    json: JSON.stringify(
      {
        mcpServers: {
          [SERVER_NAME]: { type: 'http', url: mcpUrl, headers: Object.fromEntries(headers) },
        },
      },
      null,
      2,
    ),
    skill: skillTexts(mcpUrl),
  };
}

/** Сервер плагина в Claude Code, к которому идёт вход: `plugin:<плагин>:<сервер>`. */
const CLAUDE_LOGIN_SERVER = 'plugin:casefile:casefile';

/** Адрес как сравнивает его `install.sh` (`norm_url`): `localhost` — это `127.0.0.1`, без `/` в конце. */
function normalizeUrl(url: string): string {
  return url.replace(/^(https?:\/\/)localhost/, '$1127.0.0.1').replace(/\/+$/, '');
}

/** https — любой адрес; http — только свой компьютер (`install.sh`, проверка `CASEFILE_URL`). */
function isOAuthAddress(url: string): boolean {
  return /^https:\/\/./.test(url) || /^http:\/\/(localhost|127\.0\.0\.1|\[::1\])([:/]|$)/.test(url);
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
