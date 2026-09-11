import { useId, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Trans, useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router';
import {
  ConnectionSnippets,
  LABEL_HEADER,
  TOKEN_PLACEHOLDER,
  installationQueryOptions,
} from '@/features/connect-agent';
import { CopyBlock, QueryState } from '@/shared/ui';

/**
 * Токен агента этой машины без печати куда-либо, кроме терминала человека: установка
 * держит его в файле (`docs/agent-install.md`, шаг 3). Команда одна и для установки
 * одной строкой (`~/casefile`), и для контура разработки: в обоих сервис `agent-token`
 * видит каталог `.secrets`.
 */
const AGENT_TOKEN_COMMAND =
  'docker compose run --rm --no-deps -T agent-token cat .secrets/agent-token';

/**
 * Скил дисциплины файлом для Claude Code — из самой установки, а не из сети: файл
 * `skill/tracker-agent/SKILL.md` есть у сервиса `mcp` и в образе установки
 * (`docker/Dockerfile.prod`), и в контуре разработки, где репозиторий смонтирован.
 * Ссылка на GitHub из `docs/agent-install.md` верна только для опубликованного
 * репозитория, а экран обязан работать на любой установке.
 */
const SKILL_COMMAND =
  'mkdir -p ~/.claude/skills/tracker-agent && docker compose exec -T mcp cat skill/tracker-agent/SKILL.md > ~/.claude/skills/tracker-agent/SKILL.md';

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
          <Trans t={t} i18nKey="token.ownToken" values={values} components={code} />
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
        <CopyBlock
          label={t('skill.commandLabel')}
          caption={t('skill.commandCaption')}
          text={SKILL_COMMAND}
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
