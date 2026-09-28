import { useId, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import { bootstrapQueryOptions } from '@/entities/session';
import { CLOSED_STATUSES, taskPackageQueryOptions } from '@/entities/task';
import { useUpdateOnboarding } from '@/features/manage-onboarding';
import { Button, CopyBlock } from '@/shared/ui';

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
      <h1 className="text-title">{brick('app.start')}</h1>

      <Section title={t('sections.why.title')}>
        <Text>{t('sections.why.body')}</Text>
      </Section>

      <Section title={t('sections.source.title')}>
        <Text>{t('sections.source.body')}</Text>
      </Section>

      <Section title={t('sections.tellAgent.title')}>
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

/** Раздел экрана: заголовок второго уровня и содержимое, подписанные друг другом. */
function Section({ title, children }: { title: string; children: ReactNode }) {
  const id = useId();

  return (
    <section aria-labelledby={id} className="flex min-w-0 flex-col gap-3">
      <h2 id={id} className="text-screen">
        {title}
      </h2>
      {children}
    </section>
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
