import { useTranslation } from 'react-i18next';
import type { ArchiveImportRead } from '../api/archive';

/**
 * Итог приёма: что вернул `ArchiveImportRead`, и ничего сверх этого (UI-135,
 * ограничение «не вычислять на клиенте»). Ни одно число здесь не суммируется и не
 * выводится — все они приезжают готовыми.
 *
 * Остаётся на экране, пока человек не уйдёт со страницы: приём — редкое и разовое
 * действие, и результат не должен захлопнуться раньше, чем его прочитают.
 */
export function ImportResult({ result }: { result: ArchiveImportRead }) {
  const { t } = useTranslation('moving');

  return (
    <section
      aria-label={t('import.result.label')}
      className="flex flex-col gap-3 rounded-control border border-positive-line bg-positive-soft p-4"
    >
      <p className="font-semibold text-positive">{t('import.result.done')}</p>

      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-meta">
        <dt className="text-muted">{t('import.result.revisionFrom')}</dt>
        <dd className="font-mono text-text">{result.schema_revision}</dd>

        <dt className="text-muted">{t('import.result.revisionTo')}</dt>
        <dd className="font-mono text-text">{result.head_revision}</dd>

        <dt className="text-muted">{t('import.result.machineKeys')}</dt>
        <dd className="text-text">
          {result.machine_keys.length === 0
            ? t('import.result.noMachineKeys')
            : result.machine_keys.join(', ')}
        </dd>

        <dt className="text-muted">{t('import.result.revokedSourceKeys')}</dt>
        <dd className="text-text">{result.revoked_source_keys}</dd>

        <dt className="text-muted">{t('import.result.replaced')}</dt>
        <dd className="text-text">
          {t('import.result.replacedCounts', {
            participants: result.replaced.participants,
            tokens: result.replaced.tokens,
            accounts: result.replaced.accounts,
          })}
        </dd>
      </dl>

      <div className="flex flex-col gap-1">
        <p className="text-meta text-muted">{t('import.result.tables')}</p>
        <ul className="m-0 grid grid-cols-2 gap-x-4 gap-y-0.5 p-0 text-meta fold:grid-cols-3">
          {result.tables.map((table) => (
            <li key={table.name} className="flex list-none justify-between gap-2 font-mono">
              <span className="truncate text-muted">{table.name}</span>
              <span className="text-text tabular-nums">{table.rows}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
