import { useId, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { bootstrapQueryOptions } from '@/entities/session';
import {
  ImportDialog,
  ImportResult,
  readArchiveFile,
  useExportArchive,
  type ArchiveImportRead,
  type InstallationArchiveUpload,
} from '@/features/manage-installation';
import { errorMessage } from '@/shared/errors';
import { Button, Callout, QueryState } from '@/shared/ui';

/** Файл, выбранный в поле приёма, и уже разобранное тело будущего запроса. */
interface Selected {
  file: File;
  upload: InstallationArchiveUpload;
}

/**
 * Экран «Перенос установки»: выгрузить архив всех данных этой установки и принять
 * такой же архив в свежую (`docs/moving.md`, TRK-100, UI-135).
 *
 * Только администратору — решает это флаг из первого кадра (`bootstrap.account.is_admin`),
 * а не отказ `403`: неадминистратор видит объяснение вместо кнопок, тем же образцом, что
 * и экран «Люди» (`pages/people`). На своей машине владелец тоже администратор
 * (`owner@localhost`), поэтому страж режима входа этот экран не закрывает — в отличие
 * от «Людей», перенос нужен и на одной машине без учётных записей.
 *
 * Приём необратимо заменяет все данные установки, поэтому его подтверждают в отдельном
 * окне (`ImportDialog`) — тем же образцом «спроси до, а не после», что и отзыв ключа
 * (`features/manage-access`). Файл читается и разбирается на этом экране заранее: окно
 * подтверждения не может открыться без уже выбранного файла.
 */
export function MovingPage() {
  const bootstrap = useQuery(bootstrapQueryOptions());
  const admin = bootstrap.data?.account?.is_admin === true;

  const exportArchive = useExportArchive();

  const [selected, setSelected] = useState<Selected | null>(null);
  const [parseError, setParseError] = useState<unknown>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [result, setResult] = useState<ArchiveImportRead | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { t } = useTranslation('moving');
  const { t: brick } = useTranslation('ui');
  const fileInputId = useId();
  const exportId = useId();
  const importId = useId();

  async function chooseFile(file: File | undefined) {
    setResult(null);
    setParseError(null);
    setSelected(null);
    setFileName(file?.name ?? null);
    if (file === undefined) return;

    try {
      const upload = await readArchiveFile(file);
      setSelected({ file, upload });
    } catch (cause) {
      setParseError(cause);
    }
  }

  function imported(archiveImport: ArchiveImportRead) {
    setConfirming(false);
    setResult(archiveImport);
    setSelected(null);
    setFileName(null);
    if (fileInputRef.current !== null) fileInputRef.current.value = '';
  }

  return (
    <main className="mx-auto flex max-w-(--ui-column-max) min-w-0 flex-col gap-8">
      <div className="flex flex-col gap-1">
        <h1 className="text-title">{brick('app.moving')}</h1>
        <p className="text-body text-muted">{t('intro')}</p>
      </div>

      <QueryState query={bootstrap} loading={t('loadingMe')} compact />

      {/* Пока флаг неизвестен, не говорится ничего: «закрыто» о неизвестном — выдумка. */}
      {bootstrap.data === undefined || admin ? null : <Callout>{t('notAdmin')}</Callout>}

      {!admin ? null : (
        <>
          <section aria-labelledby={exportId} className="flex flex-col gap-3">
            <h2 id={exportId} className="text-screen">
              {t('export.title')}
            </h2>
            <p className="text-body text-muted">{t('export.intro')}</p>

            <div>
              <Button disabled={exportArchive.pending} onClick={() => void exportArchive.submit()}>
                {exportArchive.pending ? t('export.pending') : t('export.action')}
              </Button>
            </div>

            {exportArchive.error === null || exportArchive.error === undefined ? null : (
              <Callout tone="danger">{errorMessage(exportArchive.error)}</Callout>
            )}
          </section>

          <section aria-labelledby={importId} className="flex flex-col gap-3">
            <h2 id={importId} className="text-screen">
              {t('import.title')}
            </h2>
            <p className="text-body text-muted">{t('import.intro')}</p>

            <div className="flex flex-col gap-1">
              <label className="text-meta text-muted" htmlFor={fileInputId}>
                {t('import.fileLabel')}
              </label>
              {/*
               * Поле выбора файла браузер подписывает сам и на своём языке («Choose File»,
               * «No file chosen») — не на языке интерфейса (UI-140). Поэтому само поле
               * скрыто для глаза, но остаётся в фокусе и у диктора, а видна своя кнопка:
               * подпись `label`, которая открывает то же окно выбора, и имя файла рядом.
               * Кольцо фокуса поля рисует кнопка — через `peer`.
               */}
              <div className="flex flex-wrap items-center gap-2">
                <input
                  ref={fileInputRef}
                  id={fileInputId}
                  type="file"
                  accept="application/json,.json"
                  onChange={(event) => void chooseFile(event.target.files?.[0])}
                  className="peer sr-only"
                />
                <Button
                  asChild
                  tone="quiet"
                  size="sm"
                  className="cursor-pointer peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-focus"
                >
                  <label htmlFor={fileInputId}>{t('import.choose')}</label>
                </Button>
                <span className="text-meta break-all text-muted">
                  {fileName ?? t('import.noFile')}
                </span>
              </div>
            </div>

            {parseError === null ? null : (
              <Callout tone="danger">{errorMessage(parseError)}</Callout>
            )}

            <div>
              <Button disabled={selected === null} onClick={() => setConfirming(true)}>
                {t('import.action')}
              </Button>
            </div>

            {result === null ? null : <ImportResult result={result} />}
          </section>
        </>
      )}

      {confirming && selected !== null ? (
        <ImportDialog
          fileName={selected.file.name}
          upload={selected.upload}
          onClose={() => setConfirming(false)}
          onImported={imported}
        />
      ) : null}
    </main>
  );
}
