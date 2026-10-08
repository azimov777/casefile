import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, type To } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { Gavel, NotebookPen, X } from 'lucide-react';
import { areaKnowledgeQueryOptions, AuthorName, EntryStateMark } from '@/entities/entry';
import { Button, Input, QueryState, RelativeTime } from '@/shared/ui';
import type { Holder } from '../api/projects';
import { knowledgeLists, type KnowledgeItem, type KnowledgeKind } from '../model/knowledge';
import { EntryForm } from './entry-form';

/** Блок-список, как «Решения» проекта: строки идут до краёв поверхности. */
const LIST_BLOCK = 'flex flex-col gap-0 rounded-control border border-line bg-surface';
const BLOCK_HEAD =
  'flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-b-line px-3 pt-3 pb-2';
const ROW = 'flex flex-col gap-1 border-b border-b-line px-3 py-2 last:border-b-0';
const REF = 'font-mono whitespace-nowrap';

/** Задержка перед поиском: слово дописывают, и запрос на каждую букву бэкенду не нужен. */
const SEARCH_DELAY_MS = 300;

interface KnowledgeSectionProps {
  /** Область, чьё знание показано. */
  holder: Holder;
  kind: KnowledgeKind;
  /** Писать «Решение» и «Заметку»: архивной области и области архивного проекта — нет. */
  canWrite: boolean;
  /** Поиск из адреса (`?q=`) и его правка. */
  search: string;
  onSearch: (text: string) => void;
  /** Адрес записи в «Деле» этой страницы: тело читается там. */
  entryHref: (no: number) => To;
}

/**
 * Вкладки знания страницы области, «Решения» и «Заметки» (TRK-660, решение TRK#59):
 * действующие записи, заменённые — по переключателю с пометкой «заменено → преемник»,
 * поиск по тексту и запись человека.
 *
 * Записи читаются одним запросом на обе вкладки (`areaKnowledgeQueryOptions`) — тем же,
 * что считает числа на вкладках. Действует ли запись и кто её заменил, говорит бэкенд
 * (`status`, `superseded_by`); здесь только раскладка и показ. Тело записи раскрывается в
 * «Деле» по ссылке: второго места, где тело показывают, у области нет.
 */
export function KnowledgeSection({
  holder,
  kind,
  canWrite,
  search,
  onSearch,
  entryHref,
}: KnowledgeSectionProps) {
  const { t } = useTranslation('area');
  const feed = useQuery(areaKnowledgeQueryOptions(holder.key, search));
  const [showSuperseded, setShowSuperseded] = useState(false);
  const [writing, setWriting] = useState(false);
  const writeButton = useRef<HTMLButtonElement>(null);
  const formPlace = useRef<HTMLDivElement>(null);
  const opened = useRef(false);
  const switchId = useId();
  const headingId = `area-${kind}`;

  /* Форма получает фокус в поле, закрытая возвращает его на кнопку (как в «Деле»). */
  useEffect(() => {
    if (writing) {
      opened.current = true;
      formPlace.current?.querySelector('textarea')?.focus();
    } else if (opened.current) {
      writeButton.current?.focus();
    }
  }, [writing]);

  // Вкладка другая — форма другого типа: открытая не переезжает.
  useEffect(() => setWriting(false), [kind]);

  const list = feed.data === undefined ? null : knowledgeLists(feed.data)[kind];
  const total = list === null ? 0 : list.inForce.length + list.superseded.length;
  const type = kind === 'decisions' ? 'decision' : 'finding';

  return (
    <section className={LIST_BLOCK} aria-labelledby={headingId}>
      <div className={BLOCK_HEAD}>
        <h2 className="text-screen" id={headingId}>
          {t(`knowledge.${kind}.title`)}
        </h2>
        {canWrite && !writing ? (
          <Button
            ref={writeButton}
            size="sm"
            className="ml-auto"
            data-write={kind}
            onClick={() => setWriting(true)}
          >
            {kind === 'decisions' ? (
              <Gavel className="size-(--ui-mark)" aria-hidden="true" />
            ) : (
              <NotebookPen className="size-(--ui-mark)" aria-hidden="true" />
            )}
            {t(kind === 'decisions' ? 'knowledge.openDecision' : 'knowledge.openNote')}
          </Button>
        ) : null}
        <p className="basis-full text-meta text-muted">{t(`knowledge.${kind}.hint`)}</p>
      </div>

      {writing ? (
        <div ref={formPlace} className="border-b border-b-line px-3 py-3">
          <EntryForm holder={holder} fixedType={type} onCancel={() => setWriting(false)} />
        </div>
      ) : null}

      <div className="border-b border-b-line px-3 py-2">
        <SearchField value={search} onSearch={onSearch} />
      </div>

      {list === null ? (
        <div className="px-3 py-2">
          <QueryState query={feed} loading={t('knowledge.loading')} />
        </div>
      ) : (
        <>
          {list.inForce.length === 0 ? (
            <p className="px-3 py-2 text-muted italic">
              {t(
                search !== ''
                  ? `knowledge.${kind}.noMatch`
                  : total === 0
                    ? `knowledge.${kind}.none`
                    : `knowledge.${kind}.noneInForce`,
              )}
            </p>
          ) : (
            <ul
              className="flex list-none flex-col p-0"
              aria-label={t(`knowledge.${kind}.list`)}
              aria-busy={feed.isFetching}
            >
              {list.inForce.map((item) => (
                <KnowledgeRow
                  key={item.entry.no}
                  holder={holder}
                  item={item}
                  entryHref={entryHref}
                />
              ))}
            </ul>
          )}

          {list.superseded.length === 0 ? null : (
            <div className="flex flex-col border-t border-t-line">
              <label
                htmlFor={switchId}
                className="flex cursor-pointer items-center gap-2 px-3 py-2 text-meta text-muted max-fold:min-h-(--ui-tap)"
              >
                <input
                  id={switchId}
                  type="checkbox"
                  className="size-(--ui-mark) accent-accent"
                  checked={showSuperseded}
                  onChange={(event) => setShowSuperseded(event.target.checked)}
                />
                <span>
                  {t('knowledge.showSuperseded')}
                  {' · '}
                  {t('knowledge.supersededCount', { count: list.superseded.length })}
                </span>
              </label>
              {showSuperseded ? (
                <ul className="flex list-none flex-col border-t border-t-line p-0">
                  {list.superseded.map((item) => (
                    <KnowledgeRow
                      key={item.entry.no}
                      holder={holder}
                      item={item}
                      entryHref={entryHref}
                    />
                  ))}
                </ul>
              ) : null}
            </div>
          )}
        </>
      )}
    </section>
  );
}

/**
 * Поле поиска: слово уходит в адрес через паузу или по Enter. Правка адреса снаружи
 * («Назад») возвращается в поле. Сброс — кнопка в поле, когда в нём что-то есть.
 */
function SearchField({ value, onSearch }: { value: string; onSearch: (text: string) => void }) {
  const { t } = useTranslation('area');
  const [draft, setDraft] = useState(value);

  useEffect(() => setDraft(value), [value]);
  useEffect(() => {
    if (draft.trim() === value) return;
    const timer = window.setTimeout(() => onSearch(draft.trim()), SEARCH_DELAY_MS);
    return () => window.clearTimeout(timer);
    // Паузой управляет только набор: смена `value` снаружи его не перезапускает.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft]);

  function submit(event: FormEvent) {
    event.preventDefault();
    onSearch(draft.trim());
  }

  return (
    <form role="search" className="flex items-center gap-2" onSubmit={submit}>
      <Input
        type="search"
        aria-label={t('knowledge.searchLabel')}
        placeholder={t('knowledge.searchPlaceholder')}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        className="max-w-(--ui-text-max)"
      />
      {draft === '' ? null : (
        <Button
          tone="quiet"
          size="sm"
          type="button"
          aria-label={t('knowledge.searchClear')}
          title={t('knowledge.searchClear')}
          onClick={() => {
            setDraft('');
            onSearch('');
          }}
        >
          <X className="size-(--ui-mark)" aria-hidden="true" />
        </Button>
      )}
    </form>
  );
}

function KnowledgeRow({
  holder,
  item,
  entryHref,
}: {
  holder: Holder;
  item: KnowledgeItem;
  entryHref: (no: number) => To;
}) {
  const { entry, state } = item;
  const superseded = state?.status === 'superseded';
  const owner = { kind: 'area', key: holder.key } as const;

  return (
    <li
      className={ROW}
      data-knowledge={`${holder.key}#${entry.no}`}
      data-status={state?.status ?? 'in_force'}
    >
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <Link to={entryHref(entry.no)} className={REF}>
          {holder.key}#{entry.no}
        </Link>
        {state === null || (entry.type !== 'decision' && entry.type !== 'finding') ? null : (
          <EntryStateMark owner={owner} state={state} kind={entry.type} showInForce />
        )}
      </div>
      {/* Заменённое зачёркнуто: запись больше не действует, но читается целиком. */}
      <p className={superseded ? 'text-muted line-through wrap-anywhere' : 'wrap-anywhere'}>
        {entry.title}
      </p>
      <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-meta text-muted">
        <AuthorName author={entry.author} />
        <RelativeTime value={entry.created_at} />
      </p>
    </li>
  );
}
