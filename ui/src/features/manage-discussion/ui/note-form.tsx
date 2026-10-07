import { useTranslation } from 'react-i18next';
import { ApiError } from '@/shared/api';
import { errorMessage, fieldReasonText } from '@/shared/errors';
import { titleFromText } from '@/shared/lib';
import { Composer } from '@/shared/ui';
import { noteDraftKey } from '../model/draft';
import { useNote } from '../model/use-discussion-actions';

/**
 * Форма «Заметка»: свободная запись человека без вопроса (`TRK#51`, п. 2) — так закрыта
 * жалоба «негде написать просто так». Заголовок записи отдельным полем не спрашивается:
 * он выводится из первой строки текста, как у замечания к задаче.
 */
export function NoteForm({ address, onCancel }: { address: string; onCancel: () => void }) {
  const note = useNote();
  const fields = note.error instanceof ApiError ? note.error.fields : null;
  const fieldReason = fields?.body ?? fields?.title;
  const { t } = useTranslation('discussions');

  return (
    <Composer
      label={t('note.formLabel', { address })}
      fieldLabel={t('note.fieldLabel')}
      storageKey={noteDraftKey(address)}
      submitLabel={t('note.submit')}
      pendingLabel={t('note.pending')}
      emptyProblem={t('note.empty')}
      placeholder={t('note.placeholder')}
      problem={fieldReason === undefined ? undefined : fieldReasonText(fieldReason)}
      isPending={note.isPending}
      onCancel={onCancel}
      failure={
        note.isError ? (
          <>
            {errorMessage(note.error)} {t('retrySafe')}
          </>
        ) : undefined
      }
      onSubmit={async (body, idempotencyKey) => {
        try {
          await note.mutateAsync({ address, title: titleFromText(body), body, idempotencyKey });
          return true;
        } catch {
          return false;
        }
      }}
    />
  );
}
