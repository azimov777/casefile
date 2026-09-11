import { describe, expect, it } from 'vitest';
import {
  LABEL_HEADER,
  LABEL_PLACEHOLDER,
  TOKEN_ENV,
  TOKEN_PLACEHOLDER,
  connectionSnippets,
  shellQuote,
  type SnippetTexts,
} from './snippets';

/**
 * Адреса нарочно не похожи на умолчание установки: фрагмент, в котором адрес зашит,
 * совпал бы с умолчанием, но не с этими.
 */
const ADDRESS = 'https://mcp.example.test:9443/casefile/mcp';
const OTHER = 'http://10.0.0.7:18605/agents';
const TOKEN = 'trk_0123456789abcdefABCDEF-_xyz';

/** Все тексты фрагментов разом — чтобы «нигде» и «везде» проверялись без пропусков. */
function texts(snippets: SnippetTexts): string[] {
  return [
    snippets.headers,
    snippets.claudeCode,
    snippets.codexFile,
    snippets.codexEnv,
    snippets.json,
    ...snippets.codexForm.map((field) => `${field.key} ${field.name ?? ''} ${field.value}`),
  ];
}

describe('фрагменты подключения', () => {
  it('адрес берётся из входа как есть, и другой адрес даёт другой текст', () => {
    const one = connectionSnippets({ mcpUrl: ADDRESS, labelled: false });
    const two = connectionSnippets({ mcpUrl: OTHER, labelled: false });

    // Адрес стоит во всех фрагментах, где клиенту нужен адрес, — целиком.
    for (const text of [one.claudeCode, one.codexFile, one.json]) expect(text).toContain(ADDRESS);
    expect(one.codexForm.find((field) => field.key === 'url')?.value).toBe(ADDRESS);
    expect(JSON.parse(one.json).mcpServers.casefile.url).toBe(ADDRESS);

    // Ничего от первого адреса во втором наборе не остаётся: адрес не собирается из
    // частей и не дописывается.
    for (const text of texts(two)) expect(text).not.toContain('mcp.example.test');
    expect(two.claudeCode).not.toBe(one.claudeCode);
    expect(two.codexFile).not.toBe(one.codexFile);
    expect(two.json).not.toBe(one.json);
    expect(JSON.parse(two.json).mcpServers.casefile.url).toBe(OTHER);
  });

  it('без токена на его месте подстановка, с токеном — сам токен', () => {
    const blank = connectionSnippets({ mcpUrl: ADDRESS, labelled: false });
    expect(blank.headers).toBe(`Authorization: Bearer ${TOKEN_PLACEHOLDER}`);
    expect(blank.claudeCode).toContain(`--header "Authorization: Bearer ${TOKEN_PLACEHOLDER}"`);
    expect(blank.codexEnv).toBe(`export ${TOKEN_ENV}="${TOKEN_PLACEHOLDER}"`);
    expect(JSON.parse(blank.json).mcpServers.casefile.headers).toEqual({
      Authorization: `Bearer ${TOKEN_PLACEHOLDER}`,
    });

    const issued = connectionSnippets({ mcpUrl: ADDRESS, token: TOKEN, labelled: false });
    expect(issued.headers).toBe(`Authorization: Bearer ${TOKEN}`);
    expect(issued.claudeCode).toContain(`--header "Authorization: Bearer ${TOKEN}"`);
    expect(issued.codexEnv).toBe(`export ${TOKEN_ENV}="${TOKEN}"`);
    expect(JSON.parse(issued.json).mcpServers.casefile.headers.Authorization).toBe(
      `Bearer ${TOKEN}`,
    );
    for (const text of texts(issued)) expect(text).not.toContain(TOKEN_PLACEHOLDER);
  });

  it('в файл Codex секрет не ложится: там только имя переменной', () => {
    const issued = connectionSnippets({ mcpUrl: ADDRESS, token: TOKEN, labelled: true });

    expect(issued.codexFile).not.toContain(TOKEN);
    expect(issued.codexFile).toBe(
      [
        '[mcp_servers.casefile]',
        `url = "${ADDRESS}"`,
        `bearer_token_env_var = "${TOKEN_ENV}"`,
        `http_headers = { "${LABEL_HEADER}" = "${LABEL_PLACEHOLDER}" }`,
      ].join('\n'),
    );
    expect(issued.codexForm.map((field) => field.value)).not.toContain(TOKEN);
  });

  it('у общего токена `X-Actor-Label` есть в каждом фрагменте, у именного — ни в одном', () => {
    const shared = connectionSnippets({ mcpUrl: ADDRESS, labelled: true });

    expect(shared.headers.split('\n')).toEqual([
      `Authorization: Bearer ${TOKEN_PLACEHOLDER}`,
      `${LABEL_HEADER}: ${LABEL_PLACEHOLDER}`,
    ]);
    expect(shared.claudeCode).toContain(`--header "${LABEL_HEADER}: ${LABEL_PLACEHOLDER}"`);
    expect(shared.codexFile).toContain(`http_headers = { "${LABEL_HEADER}" =`);
    expect(JSON.parse(shared.json).mcpServers.casefile.headers[LABEL_HEADER]).toBe(
      LABEL_PLACEHOLDER,
    );
    expect(shared.codexForm).toContainEqual({
      key: 'http_headers',
      name: LABEL_HEADER,
      value: LABEL_PLACEHOLDER,
    });

    const named = connectionSnippets({ mcpUrl: ADDRESS, labelled: false });
    for (const text of texts(named)) expect(text).not.toContain(LABEL_HEADER);
    expect(named.codexForm.map((field) => field.key)).toEqual(['url', 'bearer_token_env_var']);
  });

  it('команда Claude Code ставит заголовки после имени и адреса', () => {
    const { claudeCode } = connectionSnippets({ mcpUrl: ADDRESS, token: TOKEN, labelled: true });

    // `--header` вариадический: стоя раньше позиционных, он забрал бы имя и адрес.
    expect(claudeCode).toBe(
      `claude mcp add --transport http --scope user casefile "${ADDRESS}" ` +
        `--header "Authorization: Bearer ${TOKEN}" --header "${LABEL_HEADER}: ${LABEL_PLACEHOLDER}"`,
    );
    expect(claudeCode).not.toContain('\n');
  });

  it('JSON — форма `.mcp.json` Claude Code: `type`, `url` и `headers`', () => {
    const { json } = connectionSnippets({ mcpUrl: ADDRESS, labelled: false });

    expect(JSON.parse(json)).toEqual({
      mcpServers: {
        casefile: {
          type: 'http',
          url: ADDRESS,
          headers: { Authorization: `Bearer ${TOKEN_PLACEHOLDER}` },
        },
      },
    });
  });
});

describe('кавычки оболочки', () => {
  it('знаки, которые оболочка раскрывает внутри двойных кавычек, экранируются', () => {
    expect(shellQuote('plain')).toBe('"plain"');
    expect(shellQuote('a"b')).toBe('"a\\"b"');
    expect(shellQuote('a\\b')).toBe('"a\\\\b"');
    expect(shellQuote('$(rm -rf ~)')).toBe('"\\$(rm -rf ~)"');
    expect(shellQuote('`id`')).toBe('"\\`id\\`"');
  });

  it('адрес со знаками оболочки не становится командой', () => {
    const { claudeCode, codexFile } = connectionSnippets({
      mcpUrl: 'https://host.test/mcp?token=$HOME&x="1"',
      labelled: false,
    });

    expect(claudeCode).toContain('"https://host.test/mcp?token=\\$HOME&x=\\"1\\""');
    // В TOML своё экранирование: у базовой строки кавычка экранируется, а `$` — нет.
    expect(codexFile).toContain('url = "https://host.test/mcp?token=$HOME&x=\\"1\\""');
  });
});
