import { useId, type ReactNode } from 'react';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router';
import { questionsQueryOptions } from '@/entities/entry';
import { bootstrapQueryOptions } from '@/entities/session';
import { CLOSED_STATUSES, taskPackageQueryOptions, tasksQueryOptions } from '@/entities/task';
import { isRevoked, tokensQueryOptions } from '@/entities/token';
import { participantsQueryOptions } from '@/features/manage-access';
import {
  RestoreHintsAction,
  StartWalkAction,
  useUpdateOnboarding,
} from '@/features/manage-onboarding';
import { Badge, Button, CopyBlock } from '@/shared/ui';

/**
 * Идентификатор раздела «Что сказать агенту» — цель шага-якоря 2 (`TRK-378`). Второй
 * шаг ведёт сюда же самим адресом (`#tell-agent`), а не переходом на другой экран.
 */
const TELL_AGENT_ANCHOR = 'tell-agent';

/**
 * Ключ учебной задачи: проект у неё один, `START`, и заводит его установка при первом
 * подъёме (`TRK-370`) — отдельной задачей, которая ещё не слита. На контуре без него
 * запрос отвечает `404 task_not_found`, и это обычный случай, а не отказ (ниже).
 */
const TUTORIAL_TASK_KEY = 'START-1';

/**
 * Экран «Начало» (`TRK-361`): первый ответ новому человеку на четыре места, где он
 * застревает без единого объяснения (решение владельца `TRK-360#14`) — зачем это,
 * откуда берутся задачи, что сказать агенту, что делать самому. Экран стоит первым,
 * пока состояние знакомства учётной записи — `pending` (`app/routes/home-redirect.tsx`,
 * `TRK-360#17`), и открывается снова из панели пунктом «Начало» в любой момент.
 *
 * Порядок разделов и то, что «Начало» — главное, что должен понять человек с первого
 * взгляда (задачи заводит агент, а не он), — решение программы, и раздел «что сказать
 * агенту» поэтому не последний, а третий: он и есть действие, ради которого нужен
 * весь остальной текст.
 */
export function StartPage() {
  const bootstrap = useQuery(bootstrapQueryOptions());
  const tutorial = useQuery(taskPackageQueryOptions(TUTORIAL_TASK_KEY));
  const update = useUpdateOnboarding();
  const navigate = useNavigate();
  const { t } = useTranslation('start');
  const { t: brick } = useTranslation('ui');

  const account = bootstrap.data?.account ?? null;

  /*
   * Блок «Знакомство» молчит, когда его не за что показывать: нет проекта `START`, он
   * в архиве или задача уже закрыта — тем же приёмом, что скрывает от не-администратора
   * пункт панели (`app-side.tsx`, `isAdmin`). Это второстепенная подсказка, а не то,
   * ради чего открыт экран: ни спиннера на время запроса, ни отказа при `404` — только
   * появление, когда факты того стоят (constraints задачи, `pnpm e2e` идёт без учебного
   * проекта и ни разу его не видит).
   */
  const tutorialAvailable =
    tutorial.data !== undefined &&
    tutorial.data.task.project.archived_at === null &&
    !(CLOSED_STATUSES as readonly string[]).includes(tutorial.data.task.status);

  /*
   * Три шага (`TRK-378`): отметка «сделано» — только по ответу бэкенда, в браузере
   * не хранится ничего. Пока запрос идёт или ответил отказом, флаг остаётся `false`:
   * интерфейс не утверждает того, чего не узнал (constraints задачи), — шаг и его
   * ссылка при этом видны всегда.
   */

  // Шаг 1: агента подключали, если токеном, которым уже ходили, пользуется агент:
  // общий токен (`participant` пуст) или токен участника рода `agent`. Род берётся из
  // реестра участников, а не из автора токена: токен агента этой машины выпускает сама
  // установка, автором `tracker`, и признак «выпущен агентом» на обычной установке
  // не выполнялся бы никогда. Пока реестр не прочитан, именной токен не засчитывается:
  // интерфейс не утверждает того, чего не узнал. Отозванный токен и токен человека
  // шаг не отмечают.
  const tokens = useInfiniteQuery(tokensQueryOptions());
  const participants = useQuery(participantsQueryOptions());
  const tokenItems = tokens.data?.pages[0]?.items ?? [];
  const agentNames = new Set(
    (participants.data ?? []).filter((item) => item.kind === 'agent').map((item) => item.name),
  );
  const agentConnected =
    tokens.isSuccess &&
    tokenItems.some((item) => {
      if (isRevoked(item)) return false;
      if (item.last_used_at === null || item.last_used_at === undefined) return false;
      const owner = item.participant ?? null;
      return owner === null || agentNames.has(owner);
    });

  // Шаг 2: агент начал работу, если у него есть хоть одна задача не в `backlog`/`open`.
  const started = useQuery(
    tasksQueryOptions({ status: ['in_progress', 'waiting', 'done'], limit: 1, fields: ['status'] }),
  );
  const workStarted = started.isSuccess && started.data.items.length > 0;

  // Шаг 3: на вопрос человека уже отвечали, если история (`open: false`, адресат по
  // умолчанию — сам вошедший) отдаёт хоть одну запись.
  const answered = useInfiniteQuery(questionsQueryOptions({ open: false, limit: 1 }));
  const questionAnswered = answered.isSuccess && (answered.data?.pages[0]?.items.length ?? 0) > 0;

  function setStatus(status: 'completed' | 'skipped') {
    // Ключ без учётной записи (агент, вошедший ключом набора `task`) экран открывает
    // только из панели (constraints задачи) — ставить знакомство здесь нечему.
    if (account === null) return;
    update.mutate(
      { accountId: account.id, update: { status } },
      { onSuccess: () => void navigate('/tasks', { replace: true }) },
    );
  }

  return (
    <main className="mx-auto flex max-w-(--ui-column-max) min-w-0 flex-col gap-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-title">{brick('app.start')}</h1>
        <div className="flex flex-wrap items-center gap-3">
          {/* Видно, только когда есть что возвращать — скрыто целиком или по одному
              (`RestoreHintsAction`, TRK-362). Проход по экранам (TRK-364) — те же
              пояснения по порядку; человеку без учётной записи кнопки нет. */}
          <RestoreHintsAction />
          <StartWalkAction />
        </div>
      </div>

      <ol aria-label={t('steps.label')} className="m-0 flex list-none flex-col gap-3 p-0">
        <StepItem
          number={1}
          to="/connect"
          title={t('steps.connect.title')}
          done={agentConnected}
          doneLabel={t('steps.done')}
        />
        <StepItem
          number={2}
          to={`#${TELL_AGENT_ANCHOR}`}
          title={t('steps.tellAgent.title')}
          done={workStarted}
          doneLabel={t('steps.done')}
        />
        <StepItem
          number={3}
          to="/questions"
          title={t('steps.watch.title')}
          done={questionAnswered}
          doneLabel={t('steps.done')}
        />
      </ol>

      <Section title={t('sections.why.title')}>
        <Text>{t('sections.why.body')}</Text>
      </Section>

      <Section title={t('sections.source.title')}>
        <Text>{t('sections.source.body')}</Text>
      </Section>

      <Section id={TELL_AGENT_ANCHOR} title={t('sections.tellAgent.title')}>
        <Text>{t('sections.tellAgent.intro')}</Text>

        <div className="flex min-w-0 flex-col gap-6">
          {tutorialAvailable ? (
            <Phrase
              title={t('phrases.tutorial.title')}
              lead={t('phrases.tutorial.lead')}
              label={t('phrases.tutorial.label')}
              caption={t('phrases.tutorial.caption')}
              text={t('phrases.tutorial.text')}
            />
          ) : null}
          <Phrase
            title={t('phrases.file.title')}
            lead={t('phrases.file.lead')}
            label={t('phrases.file.label')}
            caption={t('phrases.file.caption')}
            text={t('phrases.file.text')}
          />
          {/* Между второй и третьей фразой (TRK-360#40): новая сессия теряет весь
              контекст, и об этом здесь стоит отдельный абзац — не вступление третьей
              фразы, а то, что разделяет их обе, дословно между «Завести задачи» и
              «Выполнить задачи». */}
          <Text>{t('sections.tellAgent.newSession')}</Text>
          <Phrase
            title={t('phrases.execute.title')}
            label={t('phrases.execute.label')}
            caption={t('phrases.execute.caption')}
            text={t('phrases.execute.text')}
          />
        </div>
      </Section>

      <Section title={t('sections.you.title')}>
        <Text>{t('sections.you.body')}</Text>
      </Section>

      <div className="flex flex-wrap gap-3">
        <Button tone="quiet" onClick={() => setStatus('skipped')} disabled={update.isPending}>
          {t('actions.skip')}
        </Button>
        <Button onClick={() => setStatus('completed')} disabled={update.isPending}>
          {t('actions.complete')}
        </Button>
      </div>
    </main>
  );
}

/**
 * Раздел экрана: заголовок второго уровня и содержимое, подписанные друг другом.
 *
 * `id` — необязательная цель для якорной ссылки (шаг 2, `TRK-378`), не участвует
 * в подписи раздела диктору: та остаётся на `aria-labelledby` заголовка.
 */
function Section({ id, title, children }: { id?: string; title: string; children: ReactNode }) {
  const headingId = useId();

  return (
    <section id={id} aria-labelledby={headingId} className="flex min-w-0 flex-col gap-3">
      <h2 id={headingId} className="text-screen">
        {title}
      </h2>
      {children}
    </section>
  );
}

/**
 * Один из трёх шагов первого входа (`TRK-378`): порядковый номер, ссылка на действие
 * и отметка «сделано» по факту установки. Отметка названа словом (`doneLabel`), а не
 * только цветом плашки — она читается и без цвета, и вслух.
 *
 * Ссылка-якорь того же экрана (`to` начинается с `#`) — обычный `<a>`: переход
 * остаётся на месте, и браузер сам прокручивает к разделу по его `id`. Переход на
 * другой экран — `Link` react-router, как и везде в интерфейсе.
 */
function StepItem({
  number,
  to,
  title,
  done,
  doneLabel,
}: {
  number: number;
  to: string;
  title: string;
  done: boolean;
  doneLabel: string;
}) {
  return (
    <li className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3">
      {/* Номер виден глазу; диктору его называет сам нумерованный список (`ol`,
          `aria-label`), поэтому кружок спрятан от него — иначе номер прозвучал бы
          дважды (тот же приём, что на экране «Подключить агента»). */}
      <span
        aria-hidden="true"
        className="grid size-7 place-items-center rounded-pill bg-accent-soft text-meta font-semibold text-accent"
      >
        {number}
      </span>
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        {to.startsWith('#') ? (
          <a href={to} className="text-body">
            {title}
          </a>
        ) : (
          <Link to={to} className="text-body">
            {title}
          </Link>
        )}
        {done ? <Badge tone="positive">{doneLabel}</Badge> : null}
      </div>
    </li>
  );
}

/** Абзац объяснения во всю ширину колонки — тот же приём, что на `/connect`. */
function Text({ children }: { children: ReactNode }) {
  return <p className="text-body">{children}</p>;
}

/** Одна фраза для агента: заголовок, необязательное короткое объяснение и блок копирования. */
function Phrase({
  title,
  lead,
  label,
  caption,
  text,
}: {
  title: string;
  lead?: string;
  label: string;
  caption: string;
  text: string;
}) {
  const id = useId();

  return (
    <div aria-labelledby={id} className="flex min-w-0 flex-col gap-2">
      <h3 id={id} className="text-meta font-semibold text-text">
        {title}
      </h3>
      {lead === undefined ? null : <Text>{lead}</Text>}
      <CopyBlock label={label} caption={caption} text={text} />
    </div>
  );
}
