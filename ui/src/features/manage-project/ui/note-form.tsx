import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '@/shared/api';
import { errorMessage, fieldReasonText } from '@/shared/errors';
import { titleFromText } from '@/shared/lib';
import { Composer, Receipt } from '@/shared/ui';
import { noteDraftKey } from '../model/draft';
import { useFileNote } from '../model/use-project-actions';

/**
 * Заметка человека в дело проекта (`UI-175`): та же форма записи, что у замечания к
 * задаче (`Composer`), — поле markdown, черновик, предпросмотр, отмена с вопросом о
 * непустом черновике (`UI-142`), — и то же подтверждение на её месте (`Receipt`).
 *
 * Не окно, а форма на месте: у `Composer` своё окно подтверждения отмены, и окно
 * внутри окна было бы ловушкой фокуса внутри ловушки. Заголовок записи — первая
 * строка текста (`titleFromText`), как у замечания: второе поле ради строки описи —
 * форма, которую человек закроет.
 */
export function NoteForm({ projectKey, onCancel }: { projectKey: string; onCancel: () => void }) {
  const note = useFileNote();
  const [filed, setFiled] = useState<{ entryNo: number; body: string } | null>(null);
  const fields = note.error instanceof ApiError ? note.error.fields : null;
  const fieldReason = fields?.body ?? fields?.title;
  const { t } = useTranslation('project');

  if (filed !== null) {
    return (
      <Receipt
        label={t('note.receiptLabel', { key: projectKey })}
        headline={t('note.receiptHeadline')}
        owner={{ kind: 'project', key: projectKey }}
        entryNo={filed.entryNo}
        body={filed.body}
        onClose={onCancel}
      />
    );
  }

  return (
    <Composer
      label={t('note.formLabel', { key: projectKey })}
      fieldLabel={t('note.fieldLabel')}
      storageKey={noteDraftKey(projectKey)}
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
          const entry = await note.mutateAsync({
            projectKey,
            title: titleFromText(body),
            body,
            idempotencyKey,
          });
          setFiled({ entryNo: entry.no, body });
          return true;
        } catch {
          // Что случилось, скажет `failure`; черновик при этом остаётся в форме.
          return false;
        }
      }}
    />
  );
}
