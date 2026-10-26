import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { areaHref } from '@/shared/lib';
import type { AreaDetail } from '../api/area';

/** Строка связи: адрес, название и причина — как отдал бэкенд (`reason` у входящей тоже). */
interface Row {
  address: string;
  title: string;
  reason: string;
}

/**
 * Смежные области (TRK-738, TRK~24#12): «Читать также» — куда эта область отсылает читателя
 * (`see_also`), «Ссылаются сюда» — кто отсылает к ней (`see_also_from`).
 *
 * Только чтение: связи ведут агенты через MCP, как связи задач (TRK#235), кнопок «добавить»
 * и «снять» нет. Порядок и состав — как в ответе бэкенда, клиент ничего не вычисляет
 * (TRK#244). Группа без строк не показывается; пусты обе — одна честная строка (TRK#245).
 * Строки на телефоне складываются в колонку: прокрутки вбок нет (TRK#241).
 */
export function SeeAlso({ area }: { area: Pick<AreaDetail, 'see_also' | 'see_also_from'> }) {
  const { t } = useTranslation('area');
  const out: Row[] = area.see_also ?? [];
  const incoming: Row[] = area.see_also_from ?? [];

  if (out.length === 0 && incoming.length === 0) {
    return (
      <p className="m-0 text-meta text-muted" data-see-also="empty">
        {t('seeAlso.none')}
      </p>
    );
  }

  return (
    <section aria-label={t('seeAlso.label')} className="flex flex-col gap-3" data-see-also="block">
      <Group kind="see_also" title={t('seeAlso.from')} rows={out} />
      <Group kind="see_also_from" title={t('seeAlso.to')} rows={incoming} />
    </section>
  );
}

function Group({
  kind,
  title,
  rows,
}: {
  kind: 'see_also' | 'see_also_from';
  title: string;
  rows: readonly Row[];
}) {
  if (rows.length === 0) return null;
  return (
    <div className="flex flex-col gap-1" data-see-also-group={kind}>
      <h2 className="m-0 text-label font-semibold tracking-caps text-faint uppercase">{title}</h2>
      <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
        {rows.map((row) => (
          <li
            key={row.address}
            className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 rounded-mark border border-line px-3 py-2"
          >
            <Link to={areaHref(row.address)} className="font-mono text-meta whitespace-nowrap">
              {row.address}
            </Link>
            <span className="wrap-anywhere">{row.title}</span>
            <span className="basis-full text-meta text-muted wrap-anywhere">{row.reason}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
