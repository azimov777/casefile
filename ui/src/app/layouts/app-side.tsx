import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, NavLink, useLocation, useSearchParams } from 'react-router';
import { ArrowLeftRight, Inbox, Info, KeyRound, Plug, UserRound, Users } from 'lucide-react';
import {
  bootstrapQueryOptions,
  bootstrapWithArchivedQueryOptions,
  useInstallKey,
  useInstallLocked,
} from '@/entities/session';
import { useLogout } from '@/features/auth';
import { CreateProject, useProjectRights } from '@/features/manage-project';
import { tasksHref } from '@/features/task-filters';
import { Button, QueryState } from '@/shared/ui';
import { cn, projectHref } from '@/shared/lib';
import { readPlace } from './place';
import { useShowArchived } from './show-archived';

/**
 * Содержимое боковой панели: где человек работает, кто он и жив ли поток.
 *
 * Проект — место, а не поле формы отбора (решение Д25). Раньше, чтобы перейти из `UI`
 * в `TRK`, человек разворачивал форму на 295 px, менял выпадающий список и сворачивал
 * обратно; при этом проект — первое, чем он делит работу.
 *
 * Действие, меняющее данные, здесь одно — «Новый проект» (`UI-175`, решение 8
 * `TRK-150`): проект — место панели, и заводят его там же, где его выбирают. Кнопка
 * есть только у ключа набора `main` (`useProjectRights`). С задачами панель по-прежнему
 * ничего не делает (`CONCEPT.md`, 1 и 7). Вторая кнопка — выход, и та стоит только там,
 * где человек входил сам: ключ от установки отзывать нечем.
 *
 * Флажок «Архивные проекты» (`UI-176`) данных не меняет: он добавляет в список проекты
 * в архиве, помеченные плашкой (`useShowArchived`).
 */
export function AppSide({ onNavigate }: { onNavigate?: () => void }) {
  const bootstrap = useQuery(bootstrapQueryOptions());
  const logout = useLogout();
  // Ключ отдала установка — выходить некуда: см. кнопку в самом низу панели.
  const fromInstall = useInstallKey();
  const locked = useInstallLocked();
  const [searchParams] = useSearchParams();
  const location = useLocation();
  const rights = useProjectRights();
  const [showArchived, setShowArchived] = useShowArchived();
  /*
   * Архивные проекты бэкенд из первого кадра убирает сам (TRK-160); по просьбе человека
   * панель читает кадр с ними (`include_archived`). Пока он едет, стоит прежний список:
   * пустая панель на время запроса хуже списка, дополненного через миг.
   */
  const withArchived = useQuery({ ...bootstrapWithArchivedQueryOptions(), enabled: showArchived });
  const { t } = useTranslation('ui');

  const projects =
    (showArchived ? withArchived.data?.projects : undefined) ?? bootstrap.data?.projects ?? [];
  /*
   * Учётная запись и люди — только в режиме входа (`TRK-113`). На своей машине владелец
   * тоже администратор (`owner@localhost`), но там человек один, пароля у него нет и
   * заводить некого: пункты были бы шумом (`TRK-91#39`). Люди — только администратору:
   * флаг приходит в первом кадре, и пункт, который кончился бы `403`, не показывается.
   */
  const account = locked ? (bootstrap.data?.account ?? null) : null;
  /*
   * Перенос установки (UI-135) решает флаг администратора сам по себе, не связанный
   * с режимом входа: на своей машине владелец тоже администратор (`owner@localhost`,
   * `is_admin: true`), а перенос ему нужен ровно там же, где и на сервере с учётными
   * записями, — поэтому `isAdmin` читается всегда, а не только при `locked`, в отличие
   * от `account` выше, которую здесь показывают лишь в режиме входа.
   */
  const isAdmin = bootstrap.data?.account?.is_admin === true;
  const place = readPlace(location.pathname, searchParams);
  const onList = location.pathname === '/tasks';

  /**
   * Переход в проект сохраняет вид и остальной отбор — тем же правилом, что и
   * переключатель вида. Условия берутся из адреса только на самом списке: на карточке
   * задачи и во входящей в адресе стоит чужое состояние, и тащить его в отбор нельзя.
   */
  function tasksOf(project: string): string {
    return tasksHref(onList ? searchParams : new URLSearchParams(), { project });
  }

  return (
    <div className="flex h-full flex-col gap-2 p-2">
      <span className="flex items-center gap-2 px-2 pt-1 pb-2 font-semibold tracking-[-0.01em]">
        <span
          aria-hidden="true"
          className="grid size-5 place-items-center rounded-mark bg-accent font-mono text-mark text-accent-text"
        >
          {t('app.mark')}
        </span>
        {t('app.name')}
      </span>

      <nav className="flex flex-col gap-px" aria-label={t('app.sections')}>
        <p className="mt-1 mb-0.5 ml-2 text-label font-semibold tracking-caps text-faint uppercase">
          {t('app.projects')}
        </p>

        {/* «Все задачи» — то же самое, что пустой проект в отборе: без этого пункта
            из проекта некуда вернуться, кроме как снятием чипа в форме. */}
        <SideLink to={tasksOf('')} current={place.project === null && onList} onClick={onNavigate}>
          {t('app.allTasks')}
        </SideLink>

        {projects.map((project) => {
          const onProject = place.section === 'project' && place.project === project.key;
          return (
            /*
             * Строка проекта ведёт в его задачи, знак справа — на экран самого проекта
             * (UI-174): оба — одно движение, и второго переключателя списка нет. Знак
             * стоит в той же строке, а не отдельным пунктом ниже: проект — одно место,
             * у которого два вида — работа в нём и он сам.
             */
            <div key={project.key} className="flex items-stretch gap-px [&>:first-child]:grow">
              <SideLink
                to={tasksOf(project.key)}
                current={place.project === project.key}
                title={project.title}
                onClick={onNavigate}
              >
                {/*
                 * Название проекта переносится, а не режется многоточием (UI-153): полное
                 * название было только в подсказке `title`, а на телефоне, где панель —
                 * выдвижной лист, наведения нет. Ключ стоит на первой строке названия.
                 */}
                <span className="shrink-0 font-mono">{project.key}</span>
                <span className="min-w-0 text-faint wrap-anywhere">
                  {project.title}
                  {/*
                   * Архивный помечен словом, а не только тоном: признак — `archived_at`
                   * из контракта как есть, интерфейс его не вычисляет. Плашка входит в
                   * имя ссылки, и диктор слышит «в архиве» вместе с проектом. Стоит она
                   * в строке названия, а не отдельной колонкой: колонка отнимала бы
                   * ширину у названия, и в шторке телефона оно шло бы по букве в строку.
                   * Не `Badge`: тот обрезает метку многоточием, а в узкой колонке панели
                   * от «в архиве» оставалось «в архи…». Тон — тот же `dropped`.
                   */}
                  {project.archived_at == null ? null : (
                    <>
                      {' '}
                      <span className="inline-block rounded-mark border border-dashed border-dropped-line px-1 text-label whitespace-nowrap text-dropped">
                        {t('app.archivedMark')}
                      </span>
                    </>
                  )}
                </span>
              </SideLink>
              <Link
                to={projectHref(project.key)}
                onClick={onNavigate}
                aria-label={t('app.aboutProject', { key: project.key })}
                title={t('app.aboutProject', { key: project.key })}
                aria-current={onProject ? 'page' : undefined}
                className={cn(
                  // Мишень не меньше 24 px и на столе, и на телефоне (`--ui-tap`, UI-154):
                  // знак без подписи мельче строки текста рядом.
                  'grid min-h-(--ui-tap) min-w-(--ui-tap) shrink-0 place-items-center rounded-control no-underline',
                  'transition-colors duration-(--motion-fast) ease-fast',
                  onProject
                    ? 'bg-accent-soft text-accent'
                    : 'text-faint hover:bg-sunken hover:text-text',
                )}
              >
                <Info className="size-(--ui-mark)" aria-hidden="true" />
              </Link>
            </div>
          );
        })}

        {/*
         * Флажок, а не кнопка: он ничего не меняет в данных, только то, что показано, —
         * тот же приём, что у архива задач в строке отбора списка. Виден любому набору:
         * читать архивный проект может каждый. Подпись кликабельна целиком, и мишень на
         * телефоне не меньше `--ui-tap`.
         */}
        <label className="mt-1 flex min-h-(--ui-tap) items-center gap-2 px-2 text-meta text-muted">
          <input
            type="checkbox"
            className="size-(--ui-mark) accent-accent"
            checked={showArchived}
            onChange={(event) => setShowArchived(event.target.checked)}
          />
          {t('app.showArchived')}
        </label>

        {/* Под списком, а не над ним: проекты — то, куда ходят каждый день, а заводят
            их редко. Панель на телефоне закрывается вместе с переходом на новый проект. */}
        {rights.manage ? (
          <div className="mt-1 px-2">
            <CreateProject onCreated={onNavigate} />
          </div>
        ) : null}

        <p className="mt-3 mb-0.5 ml-2 text-label font-semibold tracking-caps text-faint uppercase">
          {t('app.mine')}
        </p>

        <NavLink to="/questions" onClick={onNavigate} className={sectionLink}>
          <Inbox className="size-(--ui-mark) shrink-0" aria-hidden="true" />
          {t('app.inbox')}
          {/*
           * Счётчик читается как число с подписью, а не голой цифрой: «2» рядом со
           * словом «Входящая» диктор произнесёт как часть названия раздела. Само число
           * берётся из `bootstrap` как есть — интерфейс за бэкенд не считает.
           */}
          {bootstrap.data === undefined ? null : (
            <span
              className={cn(
                'ml-auto font-mono text-mark tabular-nums',
                bootstrap.data.open_questions > 0 ? 'font-semibold text-attention' : 'text-faint',
              )}
            >
              {/* Счётчик склоняется, а не обходится двоеточием: у русского три формы,
                  у английского две, и выбирает форму `i18next` по самому числу. */}
              <span className="sr-only">
                {t('app.openQuestions', { count: bootstrap.data.open_questions })}
              </span>
              <span aria-hidden="true">{bootstrap.data.open_questions}</span>
            </span>
          )}
        </NavLink>

        {/*
         * Установка — отдельная группа, а не ещё один пункт «Мне»: подключение агента
         * касается установки целиком, а не работы человека в проектах. Пункт — переход
         * к инструкции, данных он не меняет.
         */}
        <p className="mt-3 mb-0.5 ml-2 text-label font-semibold tracking-caps text-faint uppercase">
          {t('app.installation')}
        </p>

        <NavLink to="/connect" onClick={onNavigate} className={sectionLink}>
          <Plug className="size-(--ui-mark) shrink-0" aria-hidden="true" />
          {t('app.connect')}
        </NavLink>

        {/*
         * Доступы — вторая половина той же дороги: на «Подключить агента» человек
         * читает, чем подключаются, здесь — заводит агента, выпускает ему токен и
         * отзывает лишние. Пункт виден любым ключом: список доступов открыт и
         * набору `task`, а что из этого можно делать, говорит сам экран.
         */}
        <NavLink to="/access" onClick={onNavigate} className={sectionLink}>
          <KeyRound className="size-(--ui-mark) shrink-0" aria-hidden="true" />
          {t('app.access')}
        </NavLink>

        {/* Перенос — тоже действие над установкой целиком, и тоже только
            администратору (`403 admin_required` у обеих операций, UI-135). */}
        {isAdmin ? (
          <NavLink to="/moving" onClick={onNavigate} className={sectionLink}>
            <ArrowLeftRight className="size-(--ui-mark) shrink-0" aria-hidden="true" />
            {t('app.moving')}
          </NavLink>
        ) : null}

        {account?.is_admin === true ? (
          <NavLink to="/people" onClick={onNavigate} className={sectionLink}>
            <Users className="size-(--ui-mark) shrink-0" aria-hidden="true" />
            {t('app.people')}
          </NavLink>
        ) : null}
      </nav>

      <div className="mt-auto flex flex-col items-start gap-1 border-t border-line px-2 pt-2 text-mark">
        {/* Отказ показывается с повтором: чинить бэкенд и перезагружать вкладку —
            разные действия, и второе не должно быть единственным доступным. */}
        <QueryState query={bootstrap} loading={t('app.loadingParticipant')} compact />

        {/* Имя переносится по любому месту: подпись участника — чужая строка, её длину
            интерфейс не выбирает, а горизонтальной прокрутки быть не должно. */}
        {bootstrap.data === undefined ? null : (
          <span className="max-w-full break-all font-mono text-muted">
            {bootstrap.data.participant?.name ?? t('app.noParticipant')}
          </span>
        )}

        {/* Почта — имя входа: по ней человек узнаёт, под какой учётной записью сидит,
            когда в одном браузере бывают разные люди. Переход к своей учётной записи —
            там смена пароля. */}
        {account === null ? null : (
          <NavLink
            to="/account"
            onClick={onNavigate}
            className={(state) => cn(sectionLink(state), '-mx-2 max-w-full')}
            title={t('app.account')}
          >
            <UserRound className="size-(--ui-mark) shrink-0" aria-hidden="true" />
            <span className="sr-only">{t('app.account')}: </span>
            <span className="min-w-0 break-all">{account.email}</span>
          </NavLink>
        )}

        {/*
         * Выхода нет там, где выйти некуда. Ключ от установки человек не вводил
         * и ввести не сможет: нажатие вернуло бы его на тот же экран через секунду —
         * конфигурацию читают заново при каждой загрузке вкладки. Там, где людей
         * несколько, конфигурации с ключом нет, и кнопка стоит как стояла.
         *
         * В режиме входа по учётным записям ключ тоже «от установки» — токен сеанса,
         * который отдал вход, — но выход там закрывает сеанс на сервере, и без почты и
         * пароля ключа больше не будет (`TRK-113`).
         */}
        {fromInstall && !locked ? null : (
          <Button tone="quiet" size="sm" onClick={logout}>
            {t('app.signOut')}
          </Button>
        )}
      </div>
    </div>
  );
}

/**
 * Пункт раздела со своим адресом — входящая, подключение агента. Текущий раздел
 * `NavLink` помечает `aria-current="page"` сам, заливка идёт следом за ним.
 */
function sectionLink({ isActive }: { isActive: boolean }): string {
  return cn(
    'flex items-center gap-2 rounded-control px-2 py-1 text-meta no-underline',
    'transition-colors duration-(--motion-fast) ease-fast',
    isActive
      ? 'bg-accent-soft font-semibold text-accent'
      : 'text-muted hover:bg-sunken hover:text-text',
  );
}

/** Пункт панели. Текущее место помечено `aria-current`, а не только заливкой. */
function SideLink({
  to,
  current,
  title,
  onClick,
  children,
}: {
  to: string;
  current: boolean;
  title?: string;
  onClick?: () => void;
  children: React.ReactNode;
}) {
  return (
    <Link
      to={to}
      title={title}
      onClick={onClick}
      aria-current={current ? 'page' : undefined}
      className={cn(
        'flex min-w-0 items-baseline gap-2 overflow-hidden rounded-control px-2 py-1 text-meta no-underline',
        'transition-colors duration-(--motion-fast) ease-fast',
        current
          ? 'bg-accent-soft font-semibold text-accent'
          : 'text-muted hover:bg-sunken hover:text-text',
      )}
    >
      {children}
    </Link>
  );
}
