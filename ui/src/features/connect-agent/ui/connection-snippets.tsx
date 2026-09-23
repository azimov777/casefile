import { useId, type ReactNode } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router';
import { CopyBlock, SegmentedNav, SegmentedNavLink } from '@/shared/ui';
import { CLIENTS, CLIENT_PARAM, parseClient, withClient, type Client } from '../model/client';
import {
  CODEX_CONFIG_PATH,
  LABEL_HEADER,
  LABEL_PLACEHOLDER,
  SERVER_NAME,
  TOKEN_ENV,
  connectionSnippets,
  type CodexFormField,
  type SnippetInput,
  type SnippetTexts,
} from '../model/snippets';

/**
 * Имена из кода приходят в перевод значениями из констант среза: перевод их не
 * повторяет, и имя во фразе не разойдётся с именем во фрагменте.
 */
const values = {
  header: LABEL_HEADER,
  placeholder: LABEL_PLACEHOLDER,
  server: SERVER_NAME,
  env: TOKEN_ENV,
};

/** Ключ названия клиента в словаре: у идентификатора адреса дефис, у ключа словаря — нет. */
const CLIENT_TITLE = {
  'claude-code': 'snippets.clients.claudeCode',
  codex: 'snippets.clients.codex',
  json: 'snippets.clients.json',
  any: 'snippets.clients.any',
} as const satisfies Record<Client, string>;

/**
 * Готовые фрагменты подключения агента к MCP под клиенты: Claude Code, Codex (файл,
 * переменная окружения и поля формы), JSON `mcpServers` и любой клиент MCP.
 *
 * Клиенты разведены дорожкой `SegmentedNav`, и на виду фрагменты одного клиента — того,
 * что выбран в адресе (`?client=`, `model/client.ts`). Раньше все четыре клиента шли
 * подряд одной лентой, и нужный фрагмент тонул среди чужих (UI-131).
 *
 * Один компонент на два экрана: «Подключить агента» зовёт его без токена, и во
 * фрагментах стоит подстановка, «Доступы» (UI-106) — с только что выпущенным секретом.
 * Тексты фрагментов собирает `connectionSnippets`, здесь они только показываются: копии
 * фрагмента в разметке нет.
 *
 * Заголовок клиента — третьего уровня: компонент стоит внутри раздела экрана со своим
 * заголовком второго, а уровни идут подряд (`heading-order` у `axe`). Виден он только
 * диктору: зрячий читает то же имя на поднятой плашке дорожки прямо над ним.
 */
export function ConnectionSnippets({ mcpUrl, token, labelled }: SnippetInput) {
  const snippets = connectionSnippets({ mcpUrl, token, labelled });
  const [searchParams] = useSearchParams();
  const client = parseClient(searchParams.get(CLIENT_PARAM));
  const { t } = useTranslation('ui');

  const code = { code: <code /> };

  return (
    <div className="flex min-w-0 flex-col gap-3">
      {/*
       * Смена клиента — смена вида, а не шаг истории: `replace`, как у флажка метки.
       * На телефоне четыре клиента в строку не входят, и перенос дорожки ломал её на
       * ряд и хвост; поэтому там она сеткой два на два, а шире — одной строкой.
       *
       * `auto-rows`: сетка, в отличие от строки дорожки, высоту ряда не наследует —
       * `items-stretch` тянет ссылку по высоте ряда, а сам ряд по умолчанию высотой
       * в своё содержимое, и без минимума вкладка была 16px вместо положенных 34
       * (UI-154). Значение — то же, что даёт `SegmentedNav` без `size` (`md`,
       * `--ui-control`): свой размер сетке не выдумываю, а вкладку короче содержимого
       * `minmax` не сделает — длинное имя клиента по-прежнему растит ряд.
       */}
      <SegmentedNav
        label={t('snippets.clientNav')}
        className="grid auto-rows-[minmax(var(--ui-control),auto)] grid-cols-2 self-stretch fold:inline-flex fold:auto-rows-auto fold:self-start"
      >
        {CLIENTS.map((item) => (
          <SegmentedNavLink
            key={item}
            to={{ search: `?${withClient(searchParams, item).toString()}` }}
            replace
            preventScrollReset
            current={item === client ? 'true' : false}
          >
            {t(CLIENT_TITLE[item])}
          </SegmentedNavLink>
        ))}
      </SegmentedNav>

      {/* Метка объяснена там же, где она появилась во фрагментах: подстановку, о которой
          не сказано, чем её заменить, человек оставит как есть. */}
      {labelled ? (
        <p className="text-meta text-muted">
          <Trans t={t} i18nKey="snippets.labelHint" values={values} components={code} />
        </p>
      ) : null}

      <Client key={client} title={t(CLIENT_TITLE[client])}>
        <ClientFragments client={client} snippets={snippets} mcpUrl={mcpUrl} />
      </Client>
    </div>
  );
}

/** Объяснение и фрагменты выбранного клиента. */
function ClientFragments({
  client,
  snippets,
  mcpUrl,
}: {
  client: Client;
  snippets: SnippetTexts;
  mcpUrl: string;
}) {
  const { t } = useTranslation('ui');
  const code = { code: <code /> };

  switch (client) {
    case 'claude-code':
      return (
        <>
          <CopyBlock
            label={t('snippets.claudeLabel')}
            caption={t('snippets.terminalCaption')}
            text={snippets.claudeCode}
          />
          <Hint>
            <Trans t={t} i18nKey="snippets.claudeHint" values={values} components={code} />
          </Hint>
        </>
      );
    case 'codex':
      return (
        <>
          <Hint>
            <Trans t={t} i18nKey="snippets.codexHint" values={values} components={code} />
          </Hint>
          <CopyBlock
            label={t('snippets.codexFileLabel')}
            caption={CODEX_CONFIG_PATH}
            text={snippets.codexFile}
          />
          {/* Обе оболочки сразу, а не одна по умолчанию: угадывать оболочку по
              `navigator.userAgent` запрещено, а любое умолчание без него человек мог бы не
              заметить и скопировать нерабочую строку (`UI-114`, решение UI-114#5). */}
          <CopyBlock
            label={t('snippets.codexEnvBashLabel')}
            caption={t('snippets.codexEnvBashCaption')}
            text={snippets.codexEnv.bashZsh}
          />
          <CopyBlock
            label={t('snippets.codexEnvPowerShellLabel')}
            caption={t('snippets.codexEnvPowerShellCaption')}
            text={snippets.codexEnv.powerShell}
          />
          <CodexForm fields={snippets.codexForm} />
        </>
      );
    case 'json':
      return (
        <>
          <CopyBlock
            label={t('snippets.jsonLabel')}
            caption={t('snippets.jsonCaption')}
            text={snippets.json}
          />
          <Hint>
            <Trans t={t} i18nKey="snippets.jsonHint" values={values} components={code} />
          </Hint>
        </>
      );
    case 'any':
      return (
        <>
          <Hint>
            <Trans t={t} i18nKey="snippets.anyHint" values={values} components={code} />
          </Hint>
          <CopyBlock
            label={t('snippets.addressLabel')}
            caption={t('snippets.addressCaption')}
            text={mcpUrl}
          />
          <CopyBlock
            label={t('snippets.headersLabel')}
            caption={t('snippets.headersCaption')}
            text={snippets.headers}
          />
        </>
      );
  }
}

/** Раздел одного клиента: заголовок, объяснение и его фрагменты. */
function Client({ title, children }: { title: string; children: ReactNode }) {
  const id = useId();

  return (
    <section aria-labelledby={id} className="flex min-w-0 flex-col gap-3">
      <h3 id={id} className="sr-only">
        {title}
      </h3>
      {children}
    </section>
  );
}

/** Объяснение к фрагментам: той же ширины, что и они, — колонка у экрана одна. */
function Hint({ children }: { children: ReactNode }) {
  return <p className="text-meta text-muted">{children}</p>;
}

/**
 * Те же значения полями формы приложения Codex. Подпись поля — как её показывает
 * приложение, рядом ключ файла, на который поле ложится: документация Codex подписей
 * формы не называет, и ключ — то, по чему их можно сверить (`UI-105#14`).
 */
function CodexForm({ fields }: { fields: CodexFormField[] }) {
  const { t } = useTranslation('ui');

  return (
    <div className="flex min-w-0 flex-col gap-1">
      {/* На телефоне подпись и значение — одно под другим: в две колонки длинная подпись
          забирала ширину по своему содержимому, и адрес ломался по знаку в строку. */}
      {/* Подпись абзацем перед списком, а не `aria-labelledby` на нём: у `dl` нет роли,
          которой имя разрешено, и `axe` назвал бы его запрещённым атрибутом. */}
      <p className="text-meta text-muted">{t('snippets.codexFormHint')}</p>
      <dl className="grid min-w-0 grid-cols-1 gap-x-4 gap-y-1 rounded-control fold:grid-cols-[minmax(0,auto)_minmax(0,1fr)] border border-line bg-surface px-3 py-2 text-meta">
        {fields.map((field) => (
          <div key={field.key} className="contents">
            <dt className="text-muted">
              {t(`snippets.codexField.${field.key}`)}{' '}
              <code className="text-faint">{field.key}</code>
            </dt>
            <dd className="font-mono wrap-anywhere text-text">
              {field.name === null ? field.value : `${field.name}: ${field.value}`}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
