import { useCallback, useId, useState } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router';
import {
  FileDownloadButton,
  FileImageDialog,
  FileItem,
  filesQueryOptions,
  isImage,
  type FileCard,
} from '@/entities/file';
import { bootstrapWithArchivedQueryOptions } from '@/entities/session';
import {
  DeleteDialog,
  DeleteManyDialog,
  ReplaceDialog,
  UploadDialog,
} from '@/features/manage-files';
import { ExplanationPanel, HINT_KEYS } from '@/features/manage-onboarding';
import { Button, QueryState } from '@/shared/ui';
import { activeConditions, readFileFilter, withFilter } from '../model/file-filters';
import { FilesToolbar, type FileFilterChange } from './files-toolbar';

/**
 * Экран «Файлы»: все файлы установки одним списком (TRK-739, слово владельца TRK~8#4).
 *
 * Отбор — в адресе (`q`, `project`, `type`, `sort`, `order`), список — страницами по
 * курсору. Сервер ищет, отбирает и сортирует (TRK#244): экран только показывает. Строка —
 * карточка файла без байтов; байты читаются лишь по нажатию «Открыть» и «Скачать», потому
 * что каждое чтение — открытие файла для сервера.
 *
 * Недоступное действие не показывается (TRK/ui-screens#2): у файлов архивного проекта нет
 * ни выбора, ни «Заменить», ни «Удалить»; «Открыть» у них есть — сервер байтов архива не
 * прячет. Выбор живёт в состоянии экрана и привязан к отбору: смена отбора снимает его.
 */
export function FilesPage() {
  const { t } = useTranslation('files');
  const { t: brick } = useTranslation('ui');
  const [params, setParams] = useSearchParams();
  const filter = readFileFilter(params);
  const filterKey = JSON.stringify(filter);
  const bootstrap = useQuery(bootstrapWithArchivedQueryOptions());
  const files = useInfiniteQuery(filesQueryOptions(filter));
  const [picked, setPicked] = useState<{ key: string; ids: ReadonlySet<string> }>({
    key: filterKey,
    ids: new Set(),
  });
  const listId = useId();

  const projects = bootstrap.data?.projects ?? [];
  const archivedKeys = new Set(
    projects.filter((project) => project.archived_at != null).map((project) => project.key),
  );
  const uploadTargets = projects.filter((project) => project.archived_at == null);

  const items: FileCard[] = files.data?.pages.flatMap((page) => page.items) ?? [];
  const isArchived = (file: FileCard) => archivedKeys.has(file.project_key);
  const changeable = items.filter((file) => !isArchived(file));

  // Выбор другого отбора не переживает; файл, которого в выдаче больше нет, тоже.
  const pickedIds = picked.key === filterKey ? picked.ids : new Set<string>();
  const selected = items.filter((file) => pickedIds.has(file.id));
  const everyChangeablePicked =
    changeable.length > 0 && changeable.every((file) => pickedIds.has(file.id));

  function setPickedIds(ids: Set<string>) {
    setPicked({ key: filterKey, ids });
  }

  function toggle(file: FileCard, on: boolean) {
    const next = new Set(pickedIds);
    if (on) next.add(file.id);
    else next.delete(file.id);
    setPickedIds(next);
  }

  const change = useCallback(
    (update: FileFilterChange) => {
      setParams((current) => withFilter(current, update), { replace: true });
    },
    [setParams],
  );

  const conditions = activeConditions(filter);

  return (
    <main className="mx-auto flex max-w-(--ui-column-max) min-w-0 flex-col gap-6">
      {/* Пояснение экрана — первым блоком (TRK-363). */}
      <ExplanationPanel hintKey={HINT_KEYS.files}>{t('explanation.body')}</ExplanationPanel>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-1 basis-80 flex-col gap-1">
          <h1 className="text-title">{brick('app.files')}</h1>
          <p className="max-w-(--ui-text-max) text-body text-muted">{t('intro')}</p>
        </div>
        <UploadDialog
          ready={bootstrap.data !== undefined}
          projects={uploadTargets.map((project) => ({ key: project.key, title: project.title }))}
          defaultProject={
            filter.project !== null && !archivedKeys.has(filter.project) ? filter.project : null
          }
        />
      </div>

      <FilesToolbar
        filter={filter}
        projects={projects.map((project) => ({ key: project.key, title: project.title }))}
        onChange={change}
        onReset={() =>
          setParams((current) => withFilter(current, { q: '', project: null, type: null }), {
            replace: true,
          })
        }
      />

      <QueryState
        query={files}
        loading={t('loading')}
        empty={
          items.length === 0 ? (conditions === 0 ? t('empty') : t('emptyFiltered')) : undefined
        }
      />

      {items.length === 0 ? null : (
        <section aria-labelledby={listId} className="flex min-w-0 flex-col gap-3">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <h2 id={listId} className="text-screen">
              {t('list.label')}
            </h2>
            <span className="text-meta text-muted" data-role="shown">
              {t('list.shown', { count: items.length })}
              {files.hasNextPage ? `, ${t('list.moreAvailable')}` : ''}
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-2" data-role="bulk">
            {changeable.length === 0 ? null : (
              <label className="inline-flex min-h-(--ui-tap) items-center gap-2 text-meta text-muted">
                <input
                  type="checkbox"
                  className="size-(--ui-mark) accent-accent"
                  checked={everyChangeablePicked}
                  onChange={(event) =>
                    setPickedIds(
                      event.target.checked ? new Set(changeable.map((f) => f.id)) : new Set(),
                    )
                  }
                />
                {t('selection.selectAll')}
              </label>
            )}
            {selected.length === 0 ? null : (
              <>
                <span className="text-meta text-text" role="status" data-role="selected">
                  {t('selection.selected', { count: selected.length })}
                </span>
                <Button tone="quiet" size="sm" onClick={() => setPickedIds(new Set())}>
                  {t('selection.clear')}
                </Button>
                <DeleteManyDialog
                  target={{ kind: 'selected', files: selected }}
                  triggerLabel={t('selection.deleteSelected')}
                  onDeleted={() => setPickedIds(new Set())}
                />
              </>
            )}
            {/* Проект в архиве заморожен: удалять по отбору из него нечего (TRK/ui-screens#2). */}
            {filter.project !== null && archivedKeys.has(filter.project) ? null : (
              <DeleteManyDialog
                target={{ kind: 'matching', filter }}
                triggerLabel={
                  conditions === 0 ? t('selection.deleteEverything') : t('selection.deleteMatching')
                }
                onDeleted={() => setPickedIds(new Set())}
              />
            )}
          </div>

          <ul className="flex list-none flex-col gap-2 p-0">
            {items.map((file) => {
              const frozen = isArchived(file);
              return (
                <li key={file.id}>
                  <FileItem
                    file={file}
                    archived={frozen}
                    select={
                      frozen ? undefined : (
                        <input
                          type="checkbox"
                          className="size-(--ui-mark) accent-accent"
                          aria-label={t('item.select', { name: file.name })}
                          checked={pickedIds.has(file.id)}
                          onChange={(event) => toggle(file, event.target.checked)}
                        />
                      )
                    }
                    actions={
                      <>
                        {isImage(file) ? <FileImageDialog file={file} /> : null}
                        <FileDownloadButton file={file} />
                        {frozen ? null : (
                          <>
                            <ReplaceDialog file={file} />
                            <DeleteDialog file={file} />
                          </>
                        )}
                      </>
                    }
                  />
                </li>
              );
            })}
          </ul>

          {files.hasNextPage ? (
            <div>
              <Button
                tone="quiet"
                onClick={() => void files.fetchNextPage()}
                disabled={files.isFetchingNextPage}
              >
                {files.isFetchingNextPage ? t('list.loadingMore') : t('list.more')}
              </Button>
            </div>
          ) : null}
        </section>
      )}

      {/* Проекты нужны для отбора, загрузки и признака архива; без них экран всё равно жив. */}
      {bootstrap.isError ? <QueryState query={bootstrap} loading={t('loading')} compact /> : null}
    </main>
  );
}
