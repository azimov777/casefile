import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ApiError } from '@/shared/api';
import { errorMessage, fieldReasonText } from '@/shared/errors';
import { titleFromText } from '@/shared/lib';
import { Composer, Receipt } from '@/shared/ui';
import type { Holder, HumanEntryType } from '../api/projects';
import { noteDraftKey } from '../model/draft';
import { useFileEntry } from '../model/use-project-actions';

/**
 * Типы записи, которые человек пишет в дело: в дело проекта — только заметку (`UI-175`),
 * в дело направления — заметку и решение (TRK#16, ч. 4; TRK-557).
 */
function entryTypesOf(holder: Holder): HumanEntryType[] {
  return holder.kind === 'direction' ? ['note', 'decision'] : ['note'];
}

/**
 * Запись человека в дело проекта или направления (`UI-175`, TRK-557): та же форма
 * записи, что у замечания к задаче (`Composer`), — поле markdown, черновик, предпросмотр,
 * отмена с вопросом о непустом черновике (`UI-142`), — и то же подтверждение на её месте
 * (`Receipt`).
 *
 * Не окно, а форма на месте: у `Composer` своё окно подтверждения отмены, и окно
 * внутри окна было бы ловушкой фокуса внутри ловушки. Заголовок записи — первая
 * строка текста (`titleFromText`), как у замечания: второе поле ради строки описи —
 * форма, которую человек закроет.
 *
 * У направления над полем стоит выбор типа — «заметка» или «решение»: тип меняет то, как
 * запись читают задачи направления, а не форму, поэтому поле и черновик у них общие.
 */
export function EntryForm({ holder, onCancel }: { holder: Holder; onCancel: () => void }) {
  const entry = useFileEntry();
  const types = entryTypesOf(holder);
  const [type, setType] = useState<HumanEntryType>('note');
  const [filed, setFiled] = useState<{
    entryNo: number;
    body: string;
    type: HumanEntryType;
  } | null>(null);
  const fields = entry.error instanceof ApiError ? entry.error.fields : null;
  const fieldReason = fields?.body ?? fields?.title;
  const legendId = useId();
  const { t } = useTranslation('project');
  const { t: tDirection } = useTranslation('direction');
  const direction = holder.kind === 'direction';

  if (filed !== null) {
    return (
      <Receipt
        label={
          direction
            ? tDirection(`entry.receiptLabel.${filed.type}`, { address: holder.key })
            : t('note.receiptLabel', { key: holder.key })
        }
        headline={direction ? tDirection(`entry.receipt.${filed.type}`) : t('note.receiptHeadline')}
        owner={holder}
        entryNo={filed.entryNo}
        body={filed.body}
        onClose={onCancel}
      />
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {types.length > 1 ? (
        /*
         * Выбор типа — переключатель из двух, а не выпадающий список: вариантов два, и
         * оба видны сразу. Подпись группы — `role="radiogroup"` с `aria-labelledby`, а не
         * `fieldset`: у `fieldset` своя рамка и поля браузера, которых в нашей шкале нет.
         */
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span className="text-meta text-muted" id={legendId}>
            {tDirection('entry.typeLegend')}
          </span>
          <div role="radiogroup" aria-labelledby={legendId} className="flex flex-wrap gap-x-4">
            {types.map((option) => (
              <label
                key={option}
                className="inline-flex items-center gap-1.5 text-meta max-fold:min-h-(--ui-tap)"
              >
                <input
                  type="radio"
                  name={legendId}
                  value={option}
                  checked={type === option}
                  disabled={entry.isPending}
                  onChange={() => setType(option)}
                  className="size-(--ui-mark) accent-accent"
                />
                {tDirection(`entry.type.${option}`)}
              </label>
            ))}
          </div>
        </div>
      ) : null}

      <Composer
        label={
          direction
            ? tDirection('entry.formLabel', { address: holder.key })
            : t('note.formLabel', { key: holder.key })
        }
        fieldLabel={direction ? tDirection(`entry.fieldLabel.${type}`) : t('note.fieldLabel')}
        storageKey={noteDraftKey(holder)}
        submitLabel={direction ? tDirection(`entry.submit.${type}`) : t('note.submit')}
        pendingLabel={t('note.pending')}
        emptyProblem={direction ? tDirection(`entry.empty.${type}`) : t('note.empty')}
        placeholder={direction ? tDirection(`entry.placeholder.${type}`) : t('note.placeholder')}
        problem={fieldReason === undefined ? undefined : fieldReasonText(fieldReason)}
        isPending={entry.isPending}
        onCancel={onCancel}
        failure={
          entry.isError ? (
            <>
              {errorMessage(entry.error)} {t('retrySafe')}
            </>
          ) : undefined
        }
        onSubmit={async (body, idempotencyKey) => {
          try {
            const filedEntry = await entry.mutateAsync({
              holder,
              type,
              title: titleFromText(body),
              body,
              idempotencyKey,
            });
            setFiled({ entryNo: filedEntry.no, body, type });
            return true;
          } catch {
            // Что случилось, скажет `failure`; черновик при этом остаётся в форме.
            return false;
          }
        }}
      />
    </div>
  );
}
