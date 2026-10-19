import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import type { DiscussionOption } from '@/entities/discussion';
import { Button } from '@/shared/ui';

/**
 * Варианты ответа на вопрос: радио-карточки на всю ширину над полем текста.
 *
 * Метки и тексты — ровно то, что агент положил в вопрос (`options`): интерфейс ничего не
 * выдумывает и текст вопроса не разбирает (TRK#244). Карточка — целиком метка радио:
 * касание в любом месте выбирает, высота не меньше 44 px, текст переносится и не расширяет
 * страницу. «Снять выбор» нужен, потому что нативная радиогруппа назад не снимается, а
 * ответ без выбора остаётся законным.
 */
export function OptionPicker({
  options,
  value,
  onChange,
}: {
  options: DiscussionOption[];
  value: string | null;
  onChange: (label: string | null) => void;
}) {
  const { t } = useTranslation('discussions');
  const legendId = useId();
  const name = useId();

  return (
    <div className="flex flex-col gap-2" role="radiogroup" aria-labelledby={legendId}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span id={legendId} className="font-semibold">
          {t('reply.optionsLegend')}
        </span>
        <Button tone="quiet" size="sm" disabled={value === null} onClick={() => onChange(null)}>
          {t('reply.clearChoice')}
        </Button>
      </div>
      {options.map((option) => (
        <label
          key={option.label}
          data-option={option.label}
          className="flex min-h-11 cursor-pointer items-start gap-3 rounded-control border border-line-strong bg-surface px-3 py-2 has-checked:border-accent has-checked:bg-accent-soft has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-focus"
        >
          <input
            type="radio"
            name={name}
            value={option.label}
            checked={value === option.label}
            onChange={() => onChange(option.label)}
            className="mt-1 size-4 shrink-0 accent-accent"
          />
          <span className="min-w-8 shrink-0 font-bold wrap-anywhere">{option.label}</span>
          <span className="min-w-0 wrap-anywhere">{option.text}</span>
        </label>
      ))}
    </div>
  );
}
