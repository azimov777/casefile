import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '@/shared/api';
import type { FileCard, FileFilter } from '@/entities/file';
import { errorMessage } from '@/shared/errors';
import { Button, Callout, Dialog } from '@/shared/ui';
import { useAllMatching } from '../model/use-all-matching';
import { useDeleteFiles } from '../model/use-file-actions';

/** Сколько имён показывает окно списком; остальные — одной строкой «и ещё N». */
const NAMES_SHOWN = 8;

/**
 * Что удаляется: файлы, которые человек отметил, или все под отбор. Во втором случае окно
 * само дочитывает выдачу до конца и называет число — оно уходит на сервер как
 * `expected_count` (TRK#25: без названного числа удаление по отбору не выполняется).
 */
export type DeleteTarget =
  { kind: 'selected'; files: FileCard[] } | { kind: 'matching'; filter: FileFilter };

/**
 * Кнопка и окно «Удалить выбранные» / «Удалить все отобранные».
 *
 * Окно называет число файлов и сумму ссылок на них (по карточкам: `entries`, `tasks`); точное
 * число различных задач по нескольким файлам REST не отдаёт, поэтому сумма названа суммой.
 * Удаление по отбору требует отметки «удаляю ровно N» и несёт это N в запросе: отказ
 * `file_count_mismatch` значит, что число изменилось, ничего не удалено, окно называет новое.
 */
export function DeleteManyDialog({
  target,
  triggerLabel,
  onDeleted,
}: {
  target: DeleteTarget;
  /** Подпись кнопки, открывающей окно. */
  triggerLabel: string;
  onDeleted?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const { t } = useTranslation('files');

  return (
    <Dialog
      alert
      open={open}
      onOpenChange={setOpen}
      title={t('remove.confirm')}
      description={t('remove.manyIntro')}
      closeLabel={t('close')}
      trigger={<Button tone="quiet">{triggerLabel}</Button>}
    >
      <ManyForm target={target} onClose={() => setOpen(false)} onDeleted={onDeleted} />
    </Dialog>
  );
}

function ManyForm({
  target,
  onClose,
  onDeleted,
}: {
  target: DeleteTarget;
  onClose: () => void;
  onDeleted?: () => void;
}) {
  const matching = target.kind === 'matching';
  // Обход выдачи нужен только удалению по отбору; выбранные уже в руках экрана.
  const all = useAllMatching(
    matching
      ? target.filter
      : { q: '', project: null, mimeType: null, sort: 'added', descending: true, unopened: false },
    matching,
  );
  const remove = useDeleteFiles();
  const { t } = useTranslation('files');
  const [sure, setSure] = useState(false);

  const files = matching ? all.files : target.files;
  const ready = matching ? all.ready : true;
  const count = files.length;
  const entries = files.reduce((sum, file) => sum + file.entries, 0);
  const tasks = files.reduce((sum, file) => sum + file.tasks, 0);

  const mismatch =
    remove.error instanceof ApiError && remove.error.code === 'file_count_mismatch'
      ? remove.error
      : null;
  const failed = remove.error !== null && remove.error !== undefined && mismatch === null;

  function confirm() {
    const input = matching
      ? { filter: target.filter, expectedCount: count }
      : { ids: files.map((file) => file.id) };
    remove.mutate(input, {
      onSuccess: () => {
        onDeleted?.();
        onClose();
      },
      onError: () => {
        // Число изменилось: окно читает выдачу заново и просит подтвердить новое число.
        setSure(false);
        if (matching) all.retry();
      },
    });
  }

  if (matching && all.failed) {
    return (
      <>
        <Callout tone="danger">{errorMessage(all.error)}</Callout>
        <div>
          <Button tone="quiet" onClick={all.retry}>
            {t('remove.countAgain')}
          </Button>
        </div>
      </>
    );
  }

  if (!ready) return <Callout>{t('remove.counting')}</Callout>;

  return (
    <>
      <p className="text-screen" data-role="count" role="status">
        {matching ? t('remove.matchingTitle', { count }) : t('remove.manyTitle', { count })}
      </p>

      <ul className="m-0 flex list-none flex-col gap-1 p-0 text-meta" data-role="names">
        {files.slice(0, NAMES_SHOWN).map((file) => (
          <li key={file.id} className="wrap-anywhere">
            <span className="text-text">{file.name}</span>{' '}
            <span className="text-muted">{file.project_key}</span>
          </li>
        ))}
        {count > NAMES_SHOWN ? (
          <li className="text-muted">{t('remove.moreFiles', { count: count - NAMES_SHOWN })}</li>
        ) : null}
      </ul>

      <p className="text-body" data-role="refs">
        {entries === 0 ? t('remove.noRefs') : t('remove.refs', { count: entries, tasks })}
      </p>

      {matching && count > 0 ? (
        <label className="flex cursor-pointer items-baseline gap-2">
          <input
            type="checkbox"
            checked={sure}
            onChange={(event) => setSure(event.target.checked)}
          />
          <span className="text-meta">{t('remove.confirmCount', { count })}</span>
        </label>
      ) : null}

      {mismatch === null ? null : (
        <Callout tone="danger">
          {t('remove.mismatch', {
            actual: typeof mismatch.details.actual === 'number' ? mismatch.details.actual : count,
          })}
        </Callout>
      )}

      <div className="flex flex-wrap gap-2">
        <Button disabled={remove.isPending || count === 0 || (matching && !sure)} onClick={confirm}>
          {remove.isPending ? t('remove.pending') : t('remove.confirm')}
        </Button>
        <Button tone="quiet" onClick={onClose}>
          {t('cancel')}
        </Button>
      </div>

      {failed ? <Callout tone="danger">{errorMessage(remove.error)}</Callout> : null}
    </>
  );
}
