import { useId, type ReactNode } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import { CopyBlock } from '@/shared/ui';
import {
  CODEX_CONFIG_PATH,
  LABEL_HEADER,
  LABEL_PLACEHOLDER,
  SERVER_NAME,
  TOKEN_ENV,
  connectionSnippets,
  type CodexFormField,
  type SnippetInput,
} from '../model/snippets';

/**
 * Готовые фрагменты подключения агента к MCP под клиенты: любой клиент MCP, Claude
 * Code, Codex (файл, переменная окружения и поля формы) и JSON `mcpServers`.
 *
 * Один компонент на два экрана: «Подключить агента» зовёт его без токена, и во
 * фрагментах стоит подстановка, «Доступы» (UI-106) — с только что выпущенным секретом.
 * Тексты фрагментов собирает `connectionSnippets`, здесь они только показываются: копии
 * фрагмента в разметке нет.
 *
 * Заголовки клиентов — третьего уровня: компонент стоит внутри раздела экрана со своим
 * заголовком второго, а уровни идут подряд (`heading-order` у `axe`).
 */
export function ConnectionSnippets({ mcpUrl, token, labelled }: SnippetInput) {
  const snippets = connectionSnippets({ mcpUrl, token, labelled });
  const { t } = useTranslation('ui');

  // Имена из кода приходят значениями из констант среза: перевод их не повторяет, и
  // имя во фразе не разойдётся с именем во фрагменте.
  const values = {
    header: LABEL_HEADER,
    placeholder: LABEL_PLACEHOLDER,
    server: SERVER_NAME,
    env: TOKEN_ENV,
  };
  const code = { code: <code /> };

  return (
    <div className="flex min-w-0 flex-col gap-6">
      {/* Метка объяснена там же, где она появилась во фрагментах: подстановку, о которой
          не сказано, чем её заменить, человек оставит как есть. */}
      {labelled ? (
        <p className="max-w-(--ui-text-max) text-meta text-muted">
          <Trans t={t} i18nKey="snippets.labelHint" values={values} components={code} />
        </p>
      ) : null}

      <Client title={t('snippets.clients.any')}>
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
      </Client>

      <Client title={t('snippets.clients.claudeCode')}>
        <Hint>
          <Trans t={t} i18nKey="snippets.claudeHint" values={values} components={code} />
        </Hint>
        <CopyBlock
          label={t('snippets.claudeLabel')}
          caption={t('snippets.terminalCaption')}
          text={snippets.claudeCode}
        />
      </Client>

      <Client title={t('snippets.clients.codex')}>
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
      </Client>

      <Client title={t('snippets.clients.json')}>
        <Hint>
          <Trans t={t} i18nKey="snippets.jsonHint" values={values} components={code} />
        </Hint>
        <CopyBlock
          label={t('snippets.jsonLabel')}
          caption={t('snippets.jsonCaption')}
          text={snippets.json}
        />
      </Client>
    </div>
  );
}

/** Раздел одного клиента: заголовок, объяснение и его фрагменты. */
function Client({ title, children }: { title: string; children: ReactNode }) {
  const id = useId();

  return (
    <section aria-labelledby={id} className="flex min-w-0 flex-col gap-2">
      <h3 id={id} className="text-body font-semibold">
        {title}
      </h3>
      {children}
    </section>
  );
}

/** Объяснение к фрагментам: читаемой ширины, а не во всю строку. */
function Hint({ children }: { children: ReactNode }) {
  return <p className="max-w-(--ui-text-max) text-meta text-muted">{children}</p>;
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
      {/* Подпись абзацем перед списком, а не `aria-labelledby` на нём: у `dl` нет роли,
          которой имя разрешено, и `axe` назвал бы его запрещённым атрибутом. */}
      <p className="max-w-(--ui-text-max) text-meta text-muted">{t('snippets.codexFormHint')}</p>
      <dl className="grid min-w-0 grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-4 gap-y-1 rounded-control border border-line bg-surface px-3 py-2 text-meta">
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
