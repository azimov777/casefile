import { useId, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Trans, useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router';
import {
  ConnectionSnippets,
  LABEL_HEADER,
  TOKEN_PLACEHOLDER,
  installationQueryOptions,
} from '@/features/connect-agent';
import { CopyBlock, QueryState } from '@/shared/ui';
import { SKILL_COMMAND } from '../model/skill-command';

/**
 * Токен агента этой машины без печати куда-либо, кроме терминала человека: установка
 * держит его в файле (`docs/agent-install.md`, шаг 3). Команда одна и для установки
 * одной строкой (`~/casefile`), и для контура разработки: в обоих сервис `agent-token`
 * видит каталог `.secrets`.
 */
const AGENT_TOKEN_COMMAND =
  'docker compose run --rm --no-deps -T agent-token cat .secrets/agent-token';

/**
 * Экран «Подключить агента»: адрес MCP этой установки, готовые фрагменты под клиенты,
 * откуда взять токен и как установить скил дисциплины.
 *
 * Работает любым ключом, в том числе набора `task`: единственный запрос экрана —
 * `GET /api/v1/installation`, и он открыт всем. Секрета на экране нет: на месте токена
 * стоит подстановка, а сам токен человек читает у себя в терминале.
 *
 * Общий агентский токен — вид фрагментов, а не другой экран: флажок добавляет во все
 * фрагменты `X-Actor-Label` и держится адресом (`?shared=true`), как любой вид.
 */
export function ConnectPage() {
  const installation = useQuery(installationQueryOptions());
  const [searchParams, setSearchParams] = useSearchParams();
  const shared = searchParams.get('shared') === 'true';
  const { t } = useTranslation('connect');
  const { t: brick } = useTranslation('ui');

  function setShared(value: boolean) {
    const updated = new URLSearchParams(searchParams);
    if (value) updated.set('shared', 'true');
    else updated.delete('shared');
    setSearchParams(updated, { replace: true });
  }

  // Имена из кода приходят значениями из констант среза фрагментов: перевод их не
  // повторяет.
  const values = { placeholder: TOKEN_PLACEHOLDER, header: LABEL_HEADER };
  const code = { code: <code /> };

  return (
    <main className="flex max-w-(--ui-page-max) flex-col gap-6">
      <div>
        {/* Название раздела одно на панель и на заголовок экрана. */}
        <h1 className="text-title">{brick('app.connect')}</h1>
        <p className="mt-1 max-w-(--ui-text-max) text-meta text-muted">
          <Trans t={t} i18nKey="intro" values={values} components={code} />
        </p>
      </div>

      <Part title={t('token.title')}>
        <Text>
          <Trans t={t} i18nKey="token.thisMachine" values={values} components={code} />
        </Text>
        <CopyBlock
          label={t('token.commandLabel')}
          caption={t('token.commandCaption')}
          text={AGENT_TOKEN_COMMAND}
        />
        <Text>
          {/*
           * Отдельный токен выпускается на соседнем экране, и абзац ведёт туда
           * ссылкой. До UI-106 здесь стоял адрес `POST /api/v1/tokens`: выпускать
           * доступы интерфейс не умел вовсе, и человеку оставался `curl`.
           */}
          <Trans
            t={t}
            i18nKey="token.ownToken"
            values={values}
            components={{ ...code, access: <Link to="/access" /> }}
          />
        </Text>
        <Text>
          <Trans t={t} i18nKey="token.sharedToken" values={values} components={code} />
        </Text>
      </Part>

      <Part title={t('snippets.title')}>
        <label className="inline-flex cursor-pointer items-center gap-2 self-start">
          <input
            type="checkbox"
            checked={shared}
            onChange={(event) => setShared(event.target.checked)}
          />
          <span>
            <Trans t={t} i18nKey="snippets.shared" values={values} components={code} />
          </span>
        </label>

        <QueryState query={installation} loading={t('snippets.loading')} />
        {installation.data === undefined ? null : (
          <ConnectionSnippets mcpUrl={installation.data.mcp_url} labelled={shared} />
        )}
      </Part>

      <Part title={t('skill.title')}>
        <Text>
          <Trans t={t} i18nKey="skill.fromServer" values={values} components={code} />
        </Text>
        {/* Обе оболочки сразу, а не одна по умолчанию: угадывать оболочку по
            `navigator.userAgent` запрещено (`UI-114`, решение UI-114#5) — в PowerShell
            5.1 у команды свои три расхождения с bash/zsh (`UI-118`,
            `src/pages/connect/model/skill-command.ts`). */}
        <CopyBlock
          label={t('skill.commandBashLabel')}
          caption={t('skill.commandBashCaption')}
          text={SKILL_COMMAND.bashZsh}
        />
        <CopyBlock
          label={t('skill.commandPowerShellLabel')}
          caption={t('skill.commandPowerShellCaption')}
          text={SKILL_COMMAND.powerShell}
        />
        <Text>{t('skill.otherAgents')}</Text>
      </Part>
    </main>
  );
}

/** Раздел экрана: заголовок второго уровня и его содержимое. */
function Part({ title, children }: { title: string; children: ReactNode }) {
  const id = useId();

  return (
    <section aria-labelledby={id} className="flex min-w-0 flex-col gap-3">
      <h2 id={id} className="text-screen">
        {title}
      </h2>
      {children}
    </section>
  );
}

/** Абзац объяснения читаемой ширины. */
function Text({ children }: { children: ReactNode }) {
  return <p className="max-w-(--ui-text-max) text-body">{children}</p>;
}
