import { useTranslation } from 'react-i18next';
import { useLanguage, type Language } from '@/shared/i18n';

const formatters = new Map<Language, Intl.NumberFormat>();

/** Один знак после запятой, не больше: `1,5 МБ`, `48 КБ`. Форматтер строится один раз на язык. */
function numberFormat(language: Language): Intl.NumberFormat {
  let known = formatters.get(language);
  if (known === undefined) {
    known = new Intl.NumberFormat(language, { maximumFractionDigits: 1 });
    formatters.set(language, known);
  }
  return known;
}

/** Ступени размера: байты, килобайты, мегабайты, гигабайты (степени 1024). */
export const SIZE_STEPS = ['bytes', 'kilobytes', 'megabytes', 'gigabytes'] as const;

/** Число и ступень, на которой размер короче всего: `1 572 864` → `1.5` и `megabytes`. */
export function splitSize(bytes: number): { value: number; step: (typeof SIZE_STEPS)[number] } {
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < SIZE_STEPS.length - 1) {
    value /= 1024;
    index += 1;
  }
  return { value, step: SIZE_STEPS[index] ?? 'bytes' };
}

/** Размер файла словами на языке интерфейса: `48 КБ`. */
export function useFormatBytes() {
  const { t } = useTranslation('files');
  const { language } = useLanguage();

  return function format(bytes: number): string {
    const { value, step } = splitSize(bytes);
    return `${numberFormat(language).format(value)} ${t(`units.${step}`)}`;
  };
}
