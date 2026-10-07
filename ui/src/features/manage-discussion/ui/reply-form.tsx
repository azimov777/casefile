import { useTranslation } from 'react-i18next';
import { ApiError } from '@/shared/api';
import { errorMessage, fieldReasonText } from '@/shared/errors';
import { Composer } from '@/shared/ui';
import { replyDraftKey } from '../model/draft';
import { useReply } from '../model/use-discussion-actions';

/**
 * Форма «Ответить на #N»: ответ человека на вопрос обсуждения.
 *
 * Ввод, черновик и предпросмотр — общие с остальными формами записи (`Composer`). В отличие
 * от ответа в деле задачи, форма не уходит вместе с вопросом: вопрос остаётся в ленте
 * обсуждения с пометкой «отвечено», и удачную отправку форма подтверждает сама.
 */
export function ReplyForm({
  address,
  questionNo,
  onCancel,
}: {
  address: string;
  questionNo: number;
  onCancel: () => void;
}) {
  const reply = useReply();
  const fields = reply.error instanceof ApiError ? reply.error.fields : null;
  const { t } = useTranslation('discussions');

  return (
    <Composer
      label={t('reply.formLabel', { reference: `${address}#${questionNo}` })}
      fieldLabel={t('reply.fieldLabel')}
      storageKey={replyDraftKey(address, questionNo)}
      submitLabel={t('reply.submit')}
      pendingLabel={t('reply.pending')}
      emptyProblem={t('reply.empty')}
      placeholder={t('reply.placeholder')}
      problem={fields?.body === undefined ? undefined : fieldReasonText(fields.body)}
      isPending={reply.isPending}
      onCancel={onCancel}
      failure={
        reply.isError ? (
          <>
            {errorMessage(reply.error)} {t('retrySafe')}
          </>
        ) : undefined
      }
      onSubmit={async (body, idempotencyKey) => {
        try {
          await reply.mutateAsync({ address, questionNo, body, idempotencyKey });
          return true;
        } catch {
          return false;
        }
      }}
    />
  );
}
