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

/**
 * Токен агента этой машины без печати куда-либо, кроме терминала человека: установка
 * держит его в файле (`docs/agent-install.md`, шаг 3). Команда одна и для установки
 * одной строкой (`~/casefile`), и для контура разработки: в обоих сервис `agent-token`
 * видит каталог `.secrets`.
 */
const AGENT_TOKEN_COMMAND =
  'docker compose run --rm --no-deps -T agent-token cat .secrets/agent-token';

/**
 * Экран «Подключить агента»: два шага по порядку — взять токен, вставить фрагмент под
 * свой клиент. Третьего шага, ставившего скил дисциплины файлом, больше нет: сервер
 * отдаёт правила работы с трекером агенту сам при подключении, `instructions` MCP и
 * метадатой инструментов (решение владельца `TRK-140#8`, скил снят `TRK-146`, экран —
 * `UI-171`). Под списком шагов стоит одна фраза об этом вместо снятого раздела.
 *
 * Шаги — нумерованный список, а не разделы подряд (UI-131): человек, открывший экран
 * впервые, видит, с чего начать и что после чего, а ключевое действие каждого шага —
 * блок копирования — стоит первым, объяснение идёт следом. Всё на экране одной колонки
 * (`--ui-column-max`): текст и блоки кода одной ширины, справа от текста не остаётся
 * пустоты, а под ним — растянутых на всю страницу полос. Колонка стоит по центру области
 * содержимого, а не прижата к боковой панели (просьба владельца, UI-131#12).
 *
 * Работает любым ключом, в том числе набора `task`: единственный запрос экрана —
 * `GET /api/v1/installation`, и он открыт всем. Секрета на экране нет: на месте токена
 * стоит подстановка, а сам токен человек читает у себя в терминале.
 *
 * Общий агентский токен — вид фрагментов, а не другой экран: флажок добавляет во все
 * фрагменты `X-Actor-Label` и держится адресом (`?shared=true`), как любой вид; так же
 * адресом держится выбранный клиент (`?client=`).
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
    <main className="mx-auto flex max-w-(--ui-column-max) min-w-0 flex-col gap-8">
      <div className="flex flex-col gap-1">
        {/* Название раздела одно на панель и на заголовок экрана. */}
        <h1 className="text-title">{brick('app.connect')}</h1>
        <p className="text-body text-muted">
          <Trans t={t} i18nKey="intro" values={values} components={code} />
        </p>
      </div>

      <ol aria-label={t('steps')} className="m-0 flex list-none flex-col gap-8 p-0">
        <Step number={1} title={t('token.title')}>
          <Text>
            <Trans t={t} i18nKey="token.thisMachine" values={values} components={code} />
          </Text>
          <CopyBlock
            label={t('token.commandLabel')}
            caption={t('token.commandCaption')}
            text={AGENT_TOKEN_COMMAND}
          />
          <Hint>{t('token.terminalOnly')}</Hint>

          {/* Другие токены — не второй путь того же шага, а два случая в стороне от
              него: рамкой они отделены от главного, но смысл их на экране остаётся. */}
          <div className="flex flex-col gap-2 rounded-block border border-line bg-sunken px-4 py-3">
            <p className="text-meta font-semibold text-text">{t('token.otherTitle')}</p>
            <Hint>
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
            </Hint>
            <Hint>
              <Trans t={t} i18nKey="token.sharedToken" values={values} components={code} />
            </Hint>
          </div>
        </Step>

        <Step number={2} title={t('snippets.title')}>
          <Text>
            <Trans t={t} i18nKey="snippets.intro" values={values} components={code} />
          </Text>
          {/* Минимум высоты только на телефоне (`max-fold:`): та же мишень, что у
              флажков отбора (UI-154) — подпись кликабельна, но и вся строка label
              на 390 px не дотягивала до 24px. */}
          <label className="inline-flex cursor-pointer items-center gap-2 self-start text-meta max-fold:min-h-(--ui-tap)">
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
        </Step>
      </ol>

      {/* Раздел установки скила дисциплины снят (TRK-146, UI-171): скила в проекте
          больше нет, и ставить агенту нечего. Одна фраза на его месте вместо шага. */}
      <Hint>{t('discipline')}</Hint>
    </main>
  );
}

/**
 * Шаг подключения: номер на полях слева, заголовок второго уровня и содержимое.
 *
 * Номер виден глазу, а диктору его говорит сам нумерованный список («N из M»), поэтому
 * кружок от него спрятан: иначе номер прозвучал бы дважды.
 */
function Step({
  number,
  title,
  note,
  children,
}: {
  number: number;
  title: string;
  /** Пометка рядом с заголовком: «необязательно». */
  note?: string;
  children: ReactNode;
}) {
  const id = useId();

  return (
    <li className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 fold:gap-x-4">
      <span
        aria-hidden="true"
        className="grid size-7 place-items-center rounded-pill bg-accent-soft text-meta font-semibold text-accent"
      >
        {number}
      </span>
      <section aria-labelledby={id} className="flex min-w-0 flex-col gap-3">
        <h2 id={id} className="flex min-h-7 flex-wrap items-center gap-x-2 text-screen">
          {title}
          {note === undefined ? null : (
            <span className="text-meta font-normal text-muted">{note}</span>
          )}
        </h2>
        {children}
      </section>
    </li>
  );
}

/** Абзац объяснения во всю ширину колонки. */
function Text({ children }: { children: ReactNode }) {
  return <p className="text-body">{children}</p>;
}

/** Второстепенное пояснение: мельче и тише основного текста. */
function Hint({ children }: { children: ReactNode }) {
  return <p className="text-meta text-muted">{children}</p>;
}
