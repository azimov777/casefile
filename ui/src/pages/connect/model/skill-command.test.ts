import { describe, expect, it } from 'vitest';
import { SKILL_COMMAND } from './skill-command';

describe('команда установки скила', () => {
  it('bash/zsh цепляет команды `&&` и создаёт каталог флагом `-p`', () => {
    // `&&` работает в bash/zsh любой версии — в отличие от PowerShell (UI-118).
    expect(SKILL_COMMAND.bashZsh).toContain('mkdir -p ~/.claude/skills/tracker-agent &&');
    expect(SKILL_COMMAND.bashZsh).toContain(
      'docker compose exec -T mcp cat skill/tracker-agent/SKILL.md > ~/.claude/skills/tracker-agent/SKILL.md',
    );
    expect(SKILL_COMMAND.bashZsh).not.toContain('\n');
  });

  it('PowerShell не несёт `&&` — в Windows PowerShell 5.1 это ошибка разбора (UI-118)', () => {
    expect(SKILL_COMMAND.powerShell).not.toContain('&&');
    // Разделитель — `;`, который работает и в 5.1, и в 7.
    expect(SKILL_COMMAND.powerShell.split(';').length).toBeGreaterThan(1);
  });

  it('PowerShell создаёт каталог явным `-Force`, а не полагается на случайное совпадение `-p` с `-Path`', () => {
    expect(SKILL_COMMAND.powerShell).toContain('New-Item -ItemType Directory -Force -Path');
    expect(SKILL_COMMAND.powerShell).not.toContain('mkdir -p');
    expect(SKILL_COMMAND.powerShell).not.toContain(' -p ');
  });

  it('PowerShell не пишет файл через `>` или `Set-Content -Encoding utf8`: оба кладут BOM или UTF-16LE в 5.1 (UI-118)', () => {
    expect(SKILL_COMMAND.powerShell).not.toContain('>');
    expect(SKILL_COMMAND.powerShell).not.toContain('Set-Content');
    expect(SKILL_COMMAND.powerShell).not.toContain('Out-File');
    // Приём без BOM — тот же, что уже применён в `install.ps1` для `.env`.
    expect(SKILL_COMMAND.powerShell).toContain('[System.IO.File]::WriteAllText(');
    expect(SKILL_COMMAND.powerShell).toContain('[System.Text.UTF8Encoding]::new($false)');
  });

  it('PowerShell декодирует вывод `docker` явной кодировкой консоли — скил сплошь русский текст (UI-118)', () => {
    expect(SKILL_COMMAND.powerShell).toContain(
      '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8',
    );
    // Кодировка консоли выставлена до вызова docker, а не после.
    expect(SKILL_COMMAND.powerShell.indexOf('[Console]::OutputEncoding')).toBeLessThan(
      SKILL_COMMAND.powerShell.indexOf('docker compose exec'),
    );
  });

  it('оба варианта читают тот же файл и ставят его в тот же каталог агента', () => {
    for (const command of [SKILL_COMMAND.bashZsh, SKILL_COMMAND.powerShell]) {
      // Источник — общий для обеих строк: путь внутри установки, `/`, как в контейнере.
      expect(command).toContain('skill/tracker-agent/SKILL.md');
      expect(command).toContain('docker compose exec -T mcp cat');
      // Цель — тот же каталог агента, но своим разделителем пути на оболочку.
      expect(command).toContain('tracker-agent');
      expect(command).toContain('SKILL.md');
    }
    expect(SKILL_COMMAND.bashZsh).toContain('~/.claude/skills/tracker-agent');
    expect(SKILL_COMMAND.powerShell).toContain('$HOME\\.claude\\skills\\tracker-agent');
  });
});
