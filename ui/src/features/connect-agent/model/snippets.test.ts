import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  LABEL_HEADER,
  LABEL_PLACEHOLDER,
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
const LOCAL = 'http://127.0.0.1:8100/mcp';
const TOKEN = 'trk_0123456789abcdefABCDEF-_xyz';

/** Тексты фрагментов подключения плагином: ключа в них нет ни при каком входе. */
function pluginTexts(snippets: SnippetTexts): string[] {
  return [
    snippets.claudePlugin,
    snippets.codexPlugin,
    snippets.codexUrlFile ?? '',
    ...snippets.codexMarketplace.map((field) => field.value),
  ];
}

describe('фрагменты подключения', () => {
  it('адрес берётся из входа как есть, и другой адрес даёт другой текст', () => {
    const one = connectionSnippets({ mcpUrl: ADDRESS, labelled: false });
    const two = connectionSnippets({ mcpUrl: OTHER, labelled: false });

    for (const text of [one.claudePlugin, one.codexUrlFile, one.json]) {
      expect(text).toContain(ADDRESS);
    }
    expect(JSON.parse(one.json).mcpServers.casefile.url).toBe(ADDRESS);

    for (const text of [...pluginTexts(two), two.json])
      expect(text).not.toContain('mcp.example.test');
    expect(two.claudePlugin).not.toBe(one.claudePlugin);
    expect(two.codexUrlFile).not.toBe(one.codexUrlFile);
    expect(JSON.parse(two.json).mcpServers.casefile.url).toBe(OTHER);
  });

  it('Claude Code и Codex: ни `Authorization`, ни `trk_`, ни подстановки токена — при любом входе', () => {
    for (const input of [
      { mcpUrl: ADDRESS, labelled: false },
      { mcpUrl: ADDRESS, token: TOKEN, labelled: true },
      { mcpUrl: LOCAL, token: TOKEN, labelled: false },
    ]) {
      for (const text of pluginTexts(connectionSnippets(input))) {
        expect(text).not.toMatch(/Authorization|Bearer|trk_|--header/);
        expect(text).not.toContain(TOKEN_PLACEHOLDER);
        expect(text).not.toContain(LABEL_HEADER);
      }
    }
  });

  it('Claude Code: маркетплейс, плагин с адресом установки и вход OAuth', () => {
    const { claudePlugin } = connectionSnippets({ mcpUrl: ADDRESS, labelled: false });
    expect(claudePlugin.split('\n')).toEqual([
      'claude plugin marketplace add azimov777/casefile#stable --sparse .claude-plugin skills',
      `claude plugin install casefile@casefile --scope user --config "casefile_url=${ADDRESS}"`,
      'claude mcp login plugin:casefile:casefile',
    ]);
  });

  it('Codex: в команде маркетплейса есть `--sparse .codex-plugin`, вход — `codex mcp login casefile`', () => {
    const { codexPlugin } = connectionSnippets({ mcpUrl: ADDRESS, labelled: false });
    expect(codexPlugin.split('\n')).toEqual([
      'codex plugin marketplace add azimov777/casefile --ref stable --sparse .claude-plugin --sparse .codex-plugin --sparse skills',
      'codex plugin add casefile@casefile',
      'codex mcp login casefile',
    ]);
    expect(codexPlugin).toContain('--sparse .codex-plugin');
  });

  it('строки адреса в `config.toml` Codex — только когда адрес не зашит в плагин', () => {
    const other = connectionSnippets({ mcpUrl: ADDRESS, labelled: false });
    expect(other.codexUrlFile).toBe(`[mcp_servers.casefile]\nurl = "${ADDRESS}"`);
    for (const same of [LOCAL, 'http://localhost:8100/mcp', 'http://localhost:8100/mcp/']) {
      expect(connectionSnippets({ mcpUrl: same, labelled: false }).codexUrlFile).toBeNull();
    }
    // Другой порт на своей машине — уже другой адрес.
    expect(
      connectionSnippets({ mcpUrl: 'http://127.0.0.1:18100/mcp', labelled: false }).codexUrlFile,
    ).not.toBeNull();
  });

  it('вход OAuth доступен по https и на своей машине, по http вне её — нет', () => {
    const ok = (mcpUrl: string) => connectionSnippets({ mcpUrl, labelled: false }).oauthAvailable;
    expect(ok(ADDRESS)).toBe(true);
    expect(ok(LOCAL)).toBe(true);
    expect(ok('http://localhost:18100/mcp')).toBe(true);
    expect(ok('http://[::1]:8100/mcp')).toBe(true);
    expect(ok(OTHER)).toBe(false);
    expect(ok('http://localhost.evil.test/mcp')).toBe(false);
  });

  it('ключ — только в заголовках и JSON для клиентов без OAuth: подстановка без токена, секрет с ним', () => {
    const blank = connectionSnippets({ mcpUrl: ADDRESS, labelled: false });
    expect(blank.headers).toBe(`Authorization: Bearer ${TOKEN_PLACEHOLDER}`);
    expect(JSON.parse(blank.json).mcpServers.casefile.headers).toEqual({
      Authorization: `Bearer ${TOKEN_PLACEHOLDER}`,
    });

    const issued = connectionSnippets({ mcpUrl: ADDRESS, token: TOKEN, labelled: false });
    expect(issued.headers).toBe(`Authorization: Bearer ${TOKEN}`);
    expect(JSON.parse(issued.json).mcpServers.casefile.headers.Authorization).toBe(
      `Bearer ${TOKEN}`,
    );
    for (const text of [issued.headers, issued.json]) {
      expect(text).not.toContain(TOKEN_PLACEHOLDER);
    }
  });

  it('у общего токена `X-Actor-Label` есть во всех фрагментах с ключом, у именного — ни в одном', () => {
    const shared = connectionSnippets({ mcpUrl: ADDRESS, labelled: true });
    expect(shared.headers).toContain(`${LABEL_HEADER}: ${LABEL_PLACEHOLDER}`);
    expect(JSON.parse(shared.json).mcpServers.casefile.headers).toEqual({
      Authorization: `Bearer ${TOKEN_PLACEHOLDER}`,
      [LABEL_HEADER]: LABEL_PLACEHOLDER,
    });

    const named = connectionSnippets({ mcpUrl: ADDRESS, labelled: false });
    for (const text of [named.headers, named.json]) expect(text).not.toContain(LABEL_HEADER);
  });

  it('`json` — разбираемый JSON формы `mcpServers` с `type`, `url` и `headers`', () => {
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
    const { claudePlugin, codexUrlFile } = connectionSnippets({
      mcpUrl: 'https://host.test/mcp?token=$HOME&x="1"',
      labelled: false,
    });

    expect(claudePlugin).toContain('"casefile_url=https://host.test/mcp?token=\\$HOME&x=\\"1\\""');
    // В TOML своё экранирование: у базовой строки кавычка экранируется, а `$` — нет.
    expect(codexUrlFile).toContain('url = "https://host.test/mcp?token=$HOME&x=\\"1\\""');
  });
});

/** Установщик: команды плагина в нём — источник, с которым фрагменты сверяются дословно. */
const INSTALLER = resolve(__dirname, '../../../../../install.sh');

describe('команды плагина совпадают с установщиком `install.sh`', () => {
  const script = readFileSync(INSTALLER, 'utf8');
  // Адрес-метка: оболочка экранирует `$`, поэтому в установщике его место подставляется вручную.
  const { claudePlugin, codexPlugin } = connectionSnippets({ mcpUrl: 'ADDRESS', labelled: false });
  const [claudeMarket, claudeInstall, claudeLogin] = claudePlugin.split('\n');
  const [codexMarket, codexAdd, codexLogin] = codexPlugin.split('\n');

  it('Claude Code', () => {
    expect(script).toContain(claudeMarket);
    expect(script).toContain(claudeInstall!.replace('ADDRESS', '$PLUGIN_URL'));
    expect(script).toContain(claudeLogin!);
  });

  it('Codex', () => {
    expect(script).toContain(codexMarket!);
    expect(script).toContain(codexAdd!);
    expect(script).toContain(codexLogin!);
  });
});

/** Гайд агента, из которого команды скила берёт и установщик (`docs/agent-install.md`). */
const GUIDE = resolve(__dirname, '../../../../../docs/agent-install.md');

/** Гайд без ограждений кода и отступов: многострочная команда лежит в нём строками подряд. */
function guideLines(): string {
  return readFileSync(GUIDE, 'utf8')
    .split('\n')
    .filter((line) => !line.trim().startsWith('```'))
    .map((line) => line.trim())
    .join('\n');
}

describe('установка скила во фрагментах', () => {
  const skill = connectionSnippets({ mcpUrl: ADDRESS, labelled: false }).skill;

  it('команды скила совпадают с гайдом `docs/agent-install.md` байт в байт', () => {
    const guide = guideLines();
    const commands = [skill.other, skill.machine.bashZsh, skill.machine.powerShell];
    for (const command of commands) {
      expect(guide, command).toContain(command);
    }
  });

  it('поля пункта «Добавить маркетплейс» Codex согласны с флагами команды', () => {
    const { codexMarketplace, codexPlugin } = connectionSnippets({
      mcpUrl: ADDRESS,
      labelled: false,
    });
    const value = (key: string) => codexMarketplace.find((field) => field.key === key)?.value;
    expect(codexPlugin).toContain(`marketplace add ${value('source')} --ref ${value('ref')}`);
    const paths = (value('sparse') ?? '').split(', ');
    expect(paths).toContain('.codex-plugin');
    for (const path of paths) expect(codexPlugin).toContain(`--sparse ${path}`);
  });

  it('скил один для всех установок: ни адреса, ни токена, ни метки в нём нет', () => {
    const issued = connectionSnippets({
      mcpUrl: OTHER,
      token: TOKEN,
      labelled: true,
    }).skill;
    // Тот же текст при другом адресе, токене и метке: скил от входа не зависит.
    expect(issued).toEqual(skill);
    const all = JSON.stringify(issued);
    for (const foreign of [OTHER, 'mcp.example.test', TOKEN, TOKEN_PLACEHOLDER, LABEL_HEADER]) {
      expect(all).not.toContain(foreign);
    }
  });

  it('строка на машину агента оставляет только скил в обеих оболочках', () => {
    expect(skill.machine.bashZsh).toContain('CASEFILE_SKILL_ONLY=1 sh');
    expect(skill.machine.powerShell).toContain('$env:CASEFILE_SKILL_ONLY=1;');
  });
});
