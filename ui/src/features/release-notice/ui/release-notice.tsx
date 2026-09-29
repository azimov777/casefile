import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ArrowUpCircle } from 'lucide-react';
import { releaseQueryOptions } from '../api/release';

/**
 * Плашка внизу боковой панели: вышел выпуск новее этой установки (`TRK-416`).
 *
 * Показывается только по признаку `update_available` из контракта — версии интерфейс
 * не сравнивает. Нет признака, сбой запроса, загрузка — плашки нет вовсе, без
 * состояния ошибки: это подсказка, а не часть работы человека.
 *
 * Кнопки «обновить» нет: обновляет служба `updater` установки, трекер ничего не
 * запускает. Ссылка ведёт на страницу выпуска с заметками к нему.
 */
export function ReleaseNotice() {
  const release = useQuery(releaseQueryOptions());
  const { t } = useTranslation('ui');
  const state = release.data;

  if (
    state === undefined ||
    !state.update_available ||
    state.latest_version == null ||
    state.latest_url == null
  ) {
    return null;
  }

  return (
    <a
      href={state.latest_url}
      target="_blank"
      rel="noreferrer noopener"
      className="flex w-full items-start gap-2 rounded-control border border-accent-soft bg-accent-soft px-2 py-1.5 text-meta text-accent no-underline hover:border-accent"
    >
      <ArrowUpCircle className="mt-0.5 size-(--ui-mark) shrink-0" aria-hidden="true" />
      <span className="min-w-0 wrap-anywhere">
        <span className="block font-semibold">
          {t('release.available', { version: state.latest_version })}
        </span>
        <span className="block text-muted">{t('release.current', { version: state.version })}</span>
        <span className="sr-only">{t('release.newTab')}</span>
      </span>
    </a>
  );
}
