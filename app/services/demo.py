"""Демо-данные: установка, на которой видно каждый экран.

Зачем это в `services`, а не скриптом рядом с репозиторием: демо обязано проходить теми
же сценариями, что и живая работа. Скрипт, пишущий в таблицы напрямую, наполнил бы базу
задачами без служебных записей дела, без номеров записей и без ленты — то есть данными,
которых трекер породить не может, и первый же экран показал бы то, чего в жизни не
бывает.

Что наполняется (`TRK-29`):

- проект `DEMO` с описанием — общим контекстом всех его задач;
- задачи всех статусов, `in_progress` — двумя, потому что интересны обе: с живой
  сводкой и с провальным вердиктом, держащим выход в `done`; `done` — тоже двумя: вторая
  закрыта с проверкой `unverifiable`, и её предупреждение человек принял (`warning` и
  `acceptance`, TRK-561). Отложенная задача (`not_before` через неделю от посева) стоит в
  `open` последней. Новые задачи заводятся в конце, чтобы ключи прежних не сдвинулись: по
  ним ходят сквозные сценарии интерфейса;
- записи **всех** типов, включая служебные `section_changed`, `assignee_changed`,
  `link_added` и `link_removed`: экран дела иначе показывал бы половину словаря;
- атрибуты проекта с историей в его деле: заведение, изменение с причиной и снятие;
- перенос туда и обратно: отменённая задача уезжает в соседний проект `LEGACY` и
  возвращается со своим ключом, а прежний ключ `LEGACY-1` остаётся в её карточке;
  опустевший `LEGACY` уходит в архив и в списке проектов не виден;
- открытый блокирующий вопрос, адресованный человеку, — «входящая» и первый экран
  без него пусты;
- обсуждения (решение `TRK#51`): закрытое с итогом — вопрос, ответ, итог, привязка и
  отвязка задачи; открытое с вопросом к человеку — входящая по обсуждениям; заведённое
  человеком запиской — ход за агентом;
- связи всех трёх видов;
- три автора: человек, постоянный агент и временный агент, подписанный меткой.

## Идемпотентность

Признак «демо уже наполнено» — существование проекта `DEMO`. Повтор ничего не делает и
говорит об этом. Считать задачи или записи и дописывать недостающее было бы хуже: демо
— это одна связная история, и наполовину доигранная история хуже, чем отсутствующая.
"""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.participant import Participant
from app.db.models.project import Project
from app.db.models.task import Task
from app.db.repositories import ParticipantRepository, ProjectRepository, TaskRepository
from app.domain.authors import label_author
from app.domain.case import EntryType, RemarkOutcome, VerdictOutcome
from app.domain.links import LinkKind
from app.domain.participants import ParticipantKind
from app.domain.projects import normalize_project_key
from app.domain.tasks import TaskPriority, TaskStatus
from app.services import areas as areas_service
from app.services import attributes as attributes_service
from app.services import case as case_service
from app.services import discussions as discussions_service
from app.services import links as links_service
from app.services import participants as participants_service
from app.services import projects as projects_service
from app.services import tasks as tasks_service
from app.services.auth import TRACKER_ACTOR, Actor
from app.services.setup import DEFAULT_OWNER_NAME
from app.services.tasks import TaskChanges

#: Ключ демонстрационного проекта. Он же признак «демо уже наполнено».
DEMO_PROJECT_KEY = "DEMO"

#: Область демо-проекта: все его задачи, кроме одной «старой», заведены с ней (`area_required`).
DEMO_AREA = "DEMO/core"

#: Область соседнего проекта: задача, переехавшая туда, обязана назвать область целевого проекта.
_NEIGHBOUR_AREA = "LEGACY/past"

#: Соседний проект демо: в него задача переезжает и возвращается, и он уходит в архив.
DEMO_NEIGHBOUR_KEY = "LEGACY"

#: Постоянный агент демо: ему адресуемы вопросы и он подписывает большую часть записей.
DEMO_AGENT_NAME = "demo_agent"

#: Метка временного агента: у него нет строки в реестре, подпись приезжает заголовком
#: `X-Actor-Label`. В демо он есть затем, чтобы на экране дела было видно обе формы
#: identity агента (`CONCEPT.md`, 3.1), а не только именную.
DEMO_LABEL = "nightly_agent"

#: Не длиннее 320 знаков: описание едет в карточке каждой задачи (`CONCEPT.md`, 3.2).
_PROJECT_DESCRIPTION = (
    "Демонстрационный проект: на нём видно каждый экран интерфейса. Задачи ненастоящие, "
    "но собраны настоящими сценариями трекера. Кандидат для назначателя здесь ровно один: "
    "`status: open and blocked: false and open_blocking_questions: 0 and deferred: false`."
)


@dataclass(frozen=True, slots=True)
class DemoData:
    """Что наполнено. `None` в `project` означает «уже было наполнено, ничего не делали»."""

    project: Project | None
    tasks: list[Task]

    @property
    def created(self) -> bool:
        return self.project is not None


async def seed_demo(session: AsyncSession) -> DemoData:
    """Наполняет установку демонстрационными данными. Повтор ничего не делает.

    Автор каждого действия — тот, кто делал бы его в жизни: задачи ведёт агент, отвечает
    на вопросы человек, проект и участников заводит владелец установки. Подставлять
    везде одного автора было бы проще, но экран дела перестал бы показывать то, ради
    чего в записи есть подпись.
    """
    key = normalize_project_key(DEMO_PROJECT_KEY)
    if await ProjectRepository(session).get_by_key(key) is not None:
        return DemoData(project=None, tasks=[])

    human = await _human(session)
    owner = Actor(author=human.author, participant=human)
    robot = await _agent(session, owner)
    agent = Actor(author=robot.author, participant=robot)
    # Временный агент: участника за ним нет, подпись — метка. Набор `task`, как у
    # общего агентского токена, которым такой агент и ходит.
    temporary = Actor(author=label_author(DEMO_LABEL))

    project = await projects_service.create_project(
        session,
        actor=owner,
        key=DEMO_PROJECT_KEY,
        title="Демонстрация",
        description=_PROJECT_DESCRIPTION,
    )

    await areas_service.create_area(
        session,
        actor=owner,
        address=DEMO_AREA,
        title="Ядро",
        description="Основные механики демо-проекта: все его задачи лежат здесь.",
    )

    done = await _done_task(session, project, agent=agent, temporary=temporary, human=human)
    in_progress = await _in_progress_task(session, project, agent=agent, owner=owner, human=human)
    candidate = await _candidate_task(session, project, agent=agent)
    awaiting = await _awaiting_answer_task(session, project, agent=agent, human=human)
    child = await _child_task(session, project, agent=agent, parent=in_progress)
    checking = await _checking_task(
        session, project, agent=agent, temporary=temporary, blocker=in_progress
    )
    cancelled = await _cancelled_task(session, project, agent=agent)

    # Человек правит курс: замечание к уже закрытой задаче и его разбор. Одно замечание
    # разобрано и указывает на живую задачу, второе ждёт разбора — из него на экране
    # виден признак `open_remarks`.
    await _remarks_on_done(session, done, continuation=in_progress, human=human, agent=agent)

    # Связь, которую поставили и сняли: без неё в деле не появится `link_removed`, а он
    # такая же часть словаря записей, как и остальные.
    await links_service.add_link(
        session, in_progress, candidate, actor=agent, kind=LinkKind.RELATES
    )
    await links_service.remove_link(
        session, in_progress, candidate, actor=agent, kind=LinkKind.RELATES
    )
    await links_service.add_link(session, candidate, awaiting, actor=agent, kind=LinkKind.RELATES)

    await _attributes(session, project, agent=agent)

    # Архив и возврат из него: без них в деле проекта нет записей `archived` и `restored`.
    # Проект остаётся живым — демо показывает историю, а не замороженную доску.
    await projects_service.archive_project(
        session, project, actor=owner, reason="Пауза: демо-проект отложен до выпуска"
    )
    await projects_service.restore_project(
        session, project, actor=owner, reason="Выпуск вышел, работа над демо продолжается"
    )

    await _moved_there_and_back(session, cancelled, home=project, owner=owner)

    accepted = await _accepted_warning_task(session, project, agent=agent, human=human)
    deferred = await _deferred_task(session, project, agent=agent)
    await _discussions(session, project, agent=agent, owner=owner, human=human, deferred=deferred)

    return DemoData(
        project=project,
        tasks=[
            done,
            in_progress,
            candidate,
            awaiting,
            child,
            checking,
            cancelled,
            accepted,
            deferred,
        ],
    )


async def _attributes(session: AsyncSession, project: Project, *, agent: Actor) -> None:
    """Атрибуты проекта с историей: заведение, изменение с причиной и снятие.

    Без них в деле проекта нет ни одной из трёх записей об атрибутах, а карточка проекта
    показывала бы пустой список справочных фактов.
    """
    await attributes_service.set_attribute(
        session, project, actor=agent, name="repo", value="github.com/demo/tracker"
    )
    await attributes_service.set_attribute(
        session,
        project,
        actor=agent,
        name="branch",
        value="main",
        reason="Так названа ветка по умолчанию в git",
    )
    await attributes_service.set_attribute(
        session, project, actor=agent, name="docs", value="docs/CONCEPT.md"
    )
    await attributes_service.set_attribute(
        session,
        project,
        actor=agent,
        name="repo",
        value="github.com/demo/casefile",
        reason="Репозиторий переименован вместе с проектом",
    )
    await attributes_service.remove_attribute(
        session,
        project,
        actor=agent,
        name="docs",
        reason="Концепция переехала в описание проекта",
    )


# --- Участники ------------------------------------------------------------------------


async def _human(session: AsyncSession) -> Participant:
    """Человек, которому адресованы вопросы демо.

    Это владелец установки — тот же `owner`, которого заводит первичная инициализация.
    Заводится здесь только если демо запустили на базе без `init`: иначе блокирующий
    вопрос ушёл бы участнику, чьего токена ни у кого нет, и первый экран владельца
    показал бы ноль вопросов — ровно то, что демо обязано показать ненулевым.
    """
    existing = await ParticipantRepository(session).get_by_name(DEFAULT_OWNER_NAME)
    if existing is not None:
        return existing
    return await participants_service.register_participant(
        session,
        actor=TRACKER_ACTOR,
        kind=ParticipantKind.HUMAN,
        name=DEFAULT_OWNER_NAME,
        description="Владелец установки: смотрит задачи и отвечает на вопросы",
    )


async def _agent(session: AsyncSession, owner: Actor) -> Participant:
    """Постоянный агент демо: у него есть имя, и его можно адресовать вопросом."""
    existing = await ParticipantRepository(session).get_by_name(DEMO_AGENT_NAME)
    if existing is not None:
        return existing
    return await participants_service.register_participant(
        session,
        actor=owner,
        kind=ParticipantKind.AGENT,
        name=DEMO_AGENT_NAME,
        description="Агент демонстрационного проекта: ведёт его задачи",
    )


# --- Задачи ---------------------------------------------------------------------------


async def _done_task(
    session: AsyncSession,
    project: Project,
    *,
    agent: Actor,
    temporary: Actor,
    human: Participant,
) -> Task:
    """Закрытая задача: полный цикл от `backlog` до `done` со всеми типами записей.

    Здесь же — единственная в демо запись временного агента: провальная попытка,
    подписанная меткой. Так на экране дела видно, что у автора бывает подпись без
    строки в реестре.
    """
    task = await tasks_service.create_task(
        session,
        actor=agent,
        project=project,
        area=DEMO_AREA,
        title="Ключ задачи сгорает на отклонённом запросе",
        description=(
            "Номер выдаётся счётчиком проекта до валидации тела, поэтому запрос, "
            "отклонённый по форме, тратит номер навсегда."
        ),
        goal="Отклонённый запрос не тратит номер проекта",
        context="Номер выдаёт `projects.next_task_number`, вызов стоит первым в сценарии",
        constraints="Счётчик проекта не переписывать: номера не переиспользуются",
        output="Перенесённый вызов и тест на несгоревший номер",
        checks=[
            "Создание задачи без названия оставляет `last_task_number` прежним",
            "Полный набор тестов зелёный",
        ],
        priority=TaskPriority.NORMAL,
    )
    # Правка раздела в `backlog` — единственный статус, где содержание задачи меняется.
    await tasks_service.update_task(
        session,
        task,
        actor=agent,
        changes=TaskChanges(
            goal="Отклонённый запрос не тратит номер проекта ни при какой ошибке валидации"
        ),
    )
    await tasks_service.update_task(
        session, task, actor=agent, changes=TaskChanges(assignee=DEMO_AGENT_NAME)
    )
    # Правка обвязки: она оставляет `field_changed` — запись, без которой изменение
    # не дошло бы до ленты и до открытого экрана (`CONCEPT.md`, 4.1). После снятия меток
    # обвязка осталась одна, поэтому задача заводится с `normal` и поднимается до `high`
    # здесь: значение в наборе то же, что и было, но теперь у него есть история. Причина
    # правдоподобная — поняли, что горит; `critical` получает соседняя задача.
    await tasks_service.update_task(
        session, task, actor=agent, changes=TaskChanges(priority=TaskPriority.HIGH)
    )
    await tasks_service.transition_task(session, task, actor=agent, to=TaskStatus.OPEN)
    await tasks_service.transition_task(session, task, actor=agent, to=TaskStatus.IN_PROGRESS)

    await case_service.add_entry(
        session,
        task,
        actor=agent,
        type=EntryType.FINDING,
        title="Номер выдаётся первой строкой сценария, до нормализации полей",
        body=(
            "`create_task` зовёт `next_task_number` раньше `normalize_fields`, поэтому "
            "любой отказ валидации происходит уже после выдачи номера."
        ),
    )
    await case_service.add_entry(
        session,
        task,
        actor=temporary,
        type=EntryType.ATTEMPT,
        title="Возврат номера в счётчик при откате не работает",
        body=(
            "Пробовал уменьшать `last_task_number` в блоке отката. На параллельных "
            "созданиях два запроса получают один номер: счётчик атомарен только на "
            "выдаче. Тупик, повторять не нужно."
        ),
    )
    await case_service.add_entry(
        session,
        task,
        actor=agent,
        type=EntryType.DECISION,
        title="Номер выдаётся последним шагом, дыры в нумерации допускаются",
        body=(
            "Варианты: вернуть номер при откате (отвергнут — гонка), выдавать номер "
            "отдельной транзакцией (отвергнут — номер живёт дольше запроса), перенести "
            "вызов в конец сценария (принят). Дыры в нумерации допустимы: номера и так "
            "не переиспользуются."
        ),
    )
    await case_service.add_entry(
        session,
        task,
        actor=agent,
        type=EntryType.ARTIFACT,
        title="Правка в `app/services/tasks.py`, ветка `fix/task-key-burn`",
        body="Коммит `a1b2c3d`, диф на пятнадцать строк.",
    )
    await case_service.add_entry(
        session,
        task,
        actor=agent,
        type=EntryType.NOTE,
        title="Соседний проект заводит задачи тем же путём, его это тоже чинит",
    )
    await case_service.add_summary(
        session,
        task,
        actor=agent,
        done="Причина найдена, вызов перенесён в конец сценария, тест на несгоревший номер написан",
        remaining="Прогнать обе обзорные проверки и закрыть задачу",
        blockers="Нет",
        next_step="Подшить вердикты по обеим проверкам и перевести в `done`",
    )
    # Вердикт человека: обзорные проверки закрывает не только тот, кто вёл задачу, и
    # подшитый по ходу работы он засчитывается наравне с приехавшими в закрытии.
    await case_service.add_verdict(
        session,
        task,
        actor=Actor(author=human.author, participant=human),
        check_no=2,
        outcome=VerdictOutcome.PASSED,
        evidence="`docker compose run --rm test` — 214 passed",
    )
    # Закрытие: оставшийся вердикт и финальная сводка ложатся одной транзакцией вместе
    # со сменой статуса. Отдельного перевода в `done` в трекере нет.
    await tasks_service.close_task(
        session,
        task,
        actor=agent,
        verdicts=[
            case_service.VerdictFiling(
                check_no=1,
                outcome=VerdictOutcome.PASSED,
                evidence="Создание без названия отвечает 422, `last_task_number` остался 7",
            )
        ],
        summary=case_service.SummaryFiling(
            done="Обе обзорные проверки пройдены, номер задачи больше не сгорает",
            remaining="Ничего",
            blockers="Нет",
            next_step="Шагов нет, задача закрыта",
            unmeasured=(
                "Одновременное создание двух задач ни одной проверкой не мерилось: обе "
                "гоняют запросы по очереди. Риск считаю теоретическим — номер выдаёт "
                "последовательность в БД, — но живой гонки я не воспроизводил"
            ),
        ),
    )
    return task


async def _accepted_warning_task(
    session: AsyncSession,
    project: Project,
    *,
    agent: Actor,
    human: Participant,
) -> Task:
    """Закрытая не целиком задача: проверку нельзя было прогнать как написано.

    Закрытие с вердиктом `unverifiable` подшивает предупреждение `warning`, а человек его
    принимает записью `acceptance` (`CONCEPT.md`, 3.4; TRK-561). Принятие, а не открытое
    предупреждение, — затем, чтобы «входящая» и её значок в демо остались прежними:
    открытое предупреждение показывают сквозные сценарии на своей задаче.
    """
    task = await tasks_service.create_task(
        session,
        actor=agent,
        project=project,
        area=DEMO_AREA,
        title="Подсказка о сгоревшем номере в списке задач",
        description="Продолжение замечания к DEMO-1: дыра в нумерации видна в списке.",
        goal="Человек видит в списке, что номер задачи сгорел, а не потерян",
        context="Сгоревшие номера не хранятся: их видно только по разрыву в ключах",
        constraints="Номера не переиспользуются, счётчик проекта не трогать",
        output="Подсказка в шапке списка задач",
        checks=[
            "Тест страницы списка: подсказка видна при разрыве номеров",
            "Подсказку видно в Safari владельца на телефоне",
        ],
        assignee=DEMO_AGENT_NAME,
    )
    await tasks_service.transition_task(session, task, actor=agent, to=TaskStatus.OPEN)
    await tasks_service.transition_task(session, task, actor=agent, to=TaskStatus.IN_PROGRESS)
    await tasks_service.close_task(
        session,
        task,
        actor=agent,
        verdicts=[
            case_service.VerdictFiling(
                check_no=1,
                outcome=VerdictOutcome.PASSED,
                evidence="`pnpm test tasks-page` — 12 passed, подсказка в снимке",
            ),
            case_service.VerdictFiling(
                check_no=2,
                outcome=VerdictOutcome.UNVERIFIABLE,
                evidence=(
                    "Safari владельца агенту недоступен; прогнан Chromium на ширине "
                    "390 px — подсказка видна и не переносится"
                ),
            ),
        ],
        summary=case_service.SummaryFiling(
            done="Подсказка о сгоревшем номере есть в списке задач; Safari не проверен",
            remaining="Ничего",
            blockers="Нет",
            next_step="Шагов нет, задача закрыта",
            unmeasured="Вид в Safari на телефоне: проверка 2 закрыта как невыполнимая",
        ),
    )
    await case_service.add_entry(
        session,
        task,
        actor=Actor(author=human.author, participant=human),
        type=EntryType.ACCEPTANCE,
        title="Принято: в Safari посмотрю сам при следующем выпуске",
    )
    return task


#: На сколько демо откладывает задачу от часов базы при посеве: неделя держит её
#: отложенной, сколько бы демо ни смотрели после установки.
DEMO_DEFERRAL = timedelta(days=7)


async def _deferred_task(session: AsyncSession, project: Project, *, agent: Actor) -> Task:
    """Отложенная задача: взять её в работу раньше момента `not_before` нельзя (`TRK#47`).

    Агент взял задачу, увидел, что следующий ход возможен только через неделю, поставил
    момент «не раньше», написал сводку и ушёл в `open` с причиной, называющей момент.
    Ожидание держит поле, а не причина и не статус: до момента признак `deferred` поднят,
    кандидатом задача не считается, и вход в работу отвечает `task_deferred`. Момент — от
    часов базы при посеве, а не от календарной даты: демо, поставленное позже, иначе
    показывало бы давно наступивший момент.
    """
    task = await tasks_service.create_task(
        session,
        actor=agent,
        project=project,
        area=DEMO_AREA,
        title="Сверить карточку в каталоге после его еженедельной синхронизации",
        description="Каталог обновляет карточки раз в неделю; новое описание ещё не доехало.",
        goal="Карточка в каталоге показывает новое описание и ссылку на установку",
        context="Каталог забирает описание сам по расписанию; ускорить его нельзя",
        constraints="Описание в репозитории не менять до сверки",
        output="Запись в деле: что показывает каталог после синхронизации",
        checks=["Карточка каталога показывает новое описание и ссылку на установку"],
        assignee=DEMO_AGENT_NAME,
    )
    # Единственная «старая» задача демо — заведённая до правила `area_required`: новой
    # без области не бывает, поэтому область снимается напрямую в строке, в обход
    # сервиса. На ней видно, что задача без области читается и правится как раньше.
    task.area = None
    await session.flush()
    await tasks_service.transition_task(session, task, actor=agent, to=TaskStatus.OPEN)
    await tasks_service.transition_task(session, task, actor=agent, to=TaskStatus.IN_PROGRESS)
    moment = await TaskRepository(session).clock() + DEMO_DEFERRAL
    await tasks_service.update_task(
        session, task, actor=agent, changes=TaskChanges(not_before=moment)
    )
    await case_service.add_summary(
        session,
        task,
        actor=agent,
        done="Новое описание отправлено; каталог заберёт его при следующей синхронизации",
        remaining="Сверить карточку после синхронизации",
        blockers="Синхронизация каталога раз в неделю: раньше сверять нечего",
        next_step="Открыть карточку каталога и сравнить описание с репозиторием",
    )
    await tasks_service.transition_task(
        session,
        task,
        actor=agent,
        to=TaskStatus.OPEN,
        reason="Жду синхронизации каталога: взять не раньше момента `not_before`",
    )
    return task


async def _remarks_on_done(
    session: AsyncSession,
    done: Task,
    *,
    continuation: Task,
    human: Participant,
    agent: Actor,
) -> None:
    """Замечания человека к закрытой задаче и разбор одного из них.

    Замечание подшивается **после** закрытия намеренно: человек смотрит на сделанное и
    говорит «вышло не то», а карточка закрытой задачи от этого не меняется — меняется
    только её дело (`CONCEPT.md`, 3.4). Второе замечание остаётся без резолюции: иначе
    признак `open_remarks` был бы нулём у всех задач демо, и проверить его на экране
    было бы не на чем.
    """
    reader = Actor(author=human.author, participant=human)
    accepted = await case_service.add_entry(
        session,
        done,
        actor=reader,
        type=EntryType.REMARK,
        title="Дыры в нумерации сбивают с толку: TRK-8 есть, TRK-9 нет, TRK-10 есть",
        body=(
            "Задача закрыта и решение верное, но на экране списка это выглядит как "
            "потерянные задачи. Нужен хотя бы признак в интерфейсе, что номер сгорел."
        ),
    )
    await case_service.resolve(
        session,
        done,
        actor=agent,
        remark_no=accepted.no,
        outcome=RemarkOutcome.ACCEPTED,
        continuation=continuation.key,
        body=(
            "Согласен: дыра объяснима из дела, но не из списка. Само решение не "
            "пересматриваю — работа по признаку идёт отдельной задачей."
        ),
    )
    # Родословная: продолжение и закрытая задача видят друг друга в карточке. С закрытой
    # задачей ставится только `relates` (`CONCEPT.md`, 3.5).
    await links_service.add_link(session, continuation, done, actor=agent, kind=LinkKind.RELATES)
    await case_service.add_entry(
        session,
        done,
        actor=reader,
        type=EntryType.REMARK,
        title="В отказе не видно, какой именно номер не был выдан",
        body="Пока никто не разбирал: это второе замечание и оно ждёт своей резолюции.",
    )


async def _in_progress_task(
    session: AsyncSession,
    project: Project,
    *,
    agent: Actor,
    owner: Actor,
    human: Participant,
) -> Task:
    """Задача в работе: заданный и отвеченный вопрос, живая сводка.

    Вопрос здесь неблокирующий, и на него уже ответил человек: экран дела показывает
    пару «вопрос — ответ», а «входящая» его не показывает, потому что вопрос закрыт.
    """
    task = await tasks_service.create_task(
        session,
        actor=agent,
        project=project,
        area=DEMO_AREA,
        title="Лента журнала теряет записи при переподключении",
        description=(
            "Клиент, переподключившийся к потоку с `Last-Event-ID`, иногда пропускает "
            "одну запись — ту, что подшилась во время разрыва."
        ),
        goal="Переподключение с курсором не теряет ни одной записи",
        context="Поток отдаёт `id:` кадра равным `seq`; курсор берётся из последнего кадра",
        constraints="Формат кадра SSE не менять: он часть контракта с фронтендом",
        output="Тест на разрыв посреди потока и исправленная выборка хвоста",
        checks=["Разрыв после записи N и переподключение с `Last-Event-ID: N` отдаёт N+1"],
        assignee=DEMO_AGENT_NAME,
    )
    # Поднятый приоритет: в наборе должны быть все четыре значения, иначе различимость
    # `critical` и `normal` нечем проверить на живом контуре. Заодно это вторая запись
    # `field_changed` — правка обвязки уже после заведения задачи.
    await tasks_service.update_task(
        session, task, actor=agent, changes=TaskChanges(priority=TaskPriority.CRITICAL)
    )
    await tasks_service.transition_task(session, task, actor=agent, to=TaskStatus.OPEN)
    await tasks_service.transition_task(session, task, actor=agent, to=TaskStatus.IN_PROGRESS)
    question = await case_service.ask(
        session,
        task,
        actor=agent,
        addressees=[human.name],
        title="Считается ли пропуск записи ошибкой контракта или допустимой доставкой?",
        body="От ответа зависит, чинить ли выборку или документировать «не менее одного раза».",
        blocking=False,
    )
    await case_service.answer(
        session,
        task,
        actor=owner,
        question_no=question.no,
        body="Ошибка. Лента обещает точный хвост по `seq`, пропуск ломает цикл назначателя.",
    )
    await case_service.add_summary(
        session,
        task,
        actor=agent,
        done="Воспроизвёл разрывом соединения, причина в границе выборки хвоста",
        remaining="Поправить условие `seq > after` и написать тест на разрыв",
        blockers="Нет",
        next_step="Переписать условие выборки хвоста в `journal_page`",
    )
    return task


async def _candidate_task(session: AsyncSession, project: Project, *, agent: Actor) -> Task:
    """Свободная задача без блокеров и открытых вопросов — кандидат назначателя."""
    task = await tasks_service.create_task(
        session,
        actor=agent,
        project=project,
        area=DEMO_AREA,
        title="Ссылка на запись дела в ленте не открывает запись",
        description="В ленте ссылка `DEMO-1#3` показана текстом, перейти к записи нельзя.",
        goal="Из ленты можно перейти к записи, на которую сослались",
        context="Ссылки на записи проверяет трекер при подшивке; интерфейс показывает их строкой",
        constraints="Формат ссылок не менять: `КЛЮЧ-НОМЕР#N` уже лежит в записанных делах",
        output="Ссылка в ленте ведёт на запись дела",
        checks=["Щелчок по `DEMO-1#3` в ленте открывает дело DEMO-1 на записи №3"],
        priority=TaskPriority.LOW,
    )
    await tasks_service.transition_task(session, task, actor=agent, to=TaskStatus.OPEN)
    return task


async def _awaiting_answer_task(
    session: AsyncSession, project: Project, *, agent: Actor, human: Participant
) -> Task:
    """Задача ждёт ответа человека: сценарий `CONCEPT.md`, 4.6, строка «Ответа, долго».

    Агент упёрся в вопрос, на который сам ответить не может, задал его с признаком
    `blocking`, написал сводку и ушёл в `open` с причиной, называющей вопрос. Ожидание
    держит вопрос, а не статус: кандидатом задача не считается, пока он открыт
    (`open_blocking_questions`), и в работу её не взять (`task_has_open_blocking_questions`).
    Человек видит вопрос в своей «входящей», а саму задачу — в столбце «Ждёт ответа».
    """
    task = await tasks_service.create_task(
        session,
        actor=agent,
        project=project,
        area=DEMO_AREA,
        title="Удалять ли записи дела отменённых задач через год",
        description="Дело отменённой задачи занимает место и никем не читается.",
        goal="Решено, что делать с делами отменённых задач",
        context="Записи неизменяемы и постоянны: срока хранения в трекере нет (`CONCEPT.md`, 4.1)",
        constraints="Неизменяемость записей не трогать",
        output="Решение в деле и, если нужно, задача на реализацию",
        checks=["В деле есть запись `decision` с выбранным вариантом и отвергнутыми"],
        assignee=DEMO_AGENT_NAME,
    )
    await tasks_service.transition_task(session, task, actor=agent, to=TaskStatus.OPEN)
    await tasks_service.transition_task(session, task, actor=agent, to=TaskStatus.IN_PROGRESS)
    question = await case_service.ask(
        session,
        task,
        actor=agent,
        addressees=[human.name],
        title="Срок хранения дел отменённых задач — это решение владельца, а не агента",
        body=(
            "Концепция говорит «записи постоянны». Если это менять, менять надо "
            "концепцию, а такого права у меня нет. Сколько храним?"
        ),
        blocking=True,
    )
    await case_service.add_summary(
        session,
        task,
        actor=agent,
        done="Собрал, что говорит концепция о постоянстве записей, и что стоит за этим решением",
        remaining="Всё остальное: без ответа владельца двигаться некуда",
        blockers="Открытый блокирующий вопрос о сроке хранения",
        next_step="Дождаться ответа и подшить решение",
    )
    await tasks_service.transition_task(
        session,
        task,
        actor=agent,
        to=TaskStatus.OPEN,
        reason=f"Жду ответа владельца на {task.key}#{question.no} о сроке хранения дел",
    )
    return task


async def _child_task(
    session: AsyncSession, project: Project, *, agent: Actor, parent: Task
) -> Task:
    """Ребёнок задачи в работе: декомпозиция, ещё не открытая к работе.

    Разделы намеренно заполнены не все: задача в `backlog` — это черновик, и экран
    должен показывать, что до `open` её ещё дописывают.
    """
    task = await tasks_service.create_task(
        session,
        actor=agent,
        project=project,
        area=DEMO_AREA,
        title="Тест на разрыв потока посреди выдачи",
        description="Отдельная задача: тест требует своего стенда с обрывом соединения.",
        goal="Разрыв потока покрыт тестом",
        context="Родительская задача нашла причину; тест выделен, чтобы не смешивать правки",
    )
    # `add_link(a, b, kind=PARENT)` — «a родитель b»: родитель здесь `parent`
    # (задача в работе), а не свежесозданный `task` (TRK-97).
    await links_service.add_link(session, parent, task, actor=agent, kind=LinkKind.PARENT)
    return task


async def _checking_task(
    session: AsyncSession, project: Project, *, agent: Actor, temporary: Actor, blocker: Task
) -> Task:
    """Задача в работе на обзорных проверках: одна пройдена, вторая провалена.

    Провальный вердикт — половина словаря `VerdictOutcome` и единственное состояние, в
    котором видно, что `in_progress → done` держит именно он: экран дела без такого
    примера показывал бы только успешные заключения.

    Она же заблокирована другой задачей: связь ставится **после** входа в
    `in_progress`, потому что блокер запрещает вход в работу, а не пребывание в ней.
    """
    task = await tasks_service.create_task(
        session,
        actor=agent,
        project=project,
        area=DEMO_AREA,
        title="Ошибки поиска не называют допустимые значения",
        description="Отказ разбора запроса приходит без списка допустимых полей.",
        goal="Отказ поиска чинится с первой попытки, без перебора",
        context="Разбор живёт в `app/domain/query_language.py`, значения — в `search.py`",
        constraints="Коды ошибок не переименовывать: они часть контракта",
        output="Поля `details.allowed` у отказов разбора и подбора значений",
        checks=[
            "Незнакомое имя поля отвечает `search_field_unknown` со списком в `details.allowed`",
            "Неприменимый оператор отвечает `search_operator_not_supported` со списком",
        ],
        assignee=DEMO_LABEL,
    )
    await tasks_service.transition_task(session, task, actor=agent, to=TaskStatus.OPEN)
    # В работу задачу берёт её исполнитель — временный агент под меткой (`CONCEPT.md`,
    # 3.3): другой подписи вход в `in_progress` не пустил бы.
    await tasks_service.transition_task(session, task, actor=temporary, to=TaskStatus.IN_PROGRESS)
    await case_service.add_verdict(
        session,
        task,
        actor=agent,
        check_no=1,
        outcome=VerdictOutcome.PASSED,
        evidence=(
            "`query=stauts: open` отвечает `search_field_unknown`, в `details.allowed` десять имён"
        ),
    )
    await case_service.add_verdict(
        session,
        task,
        actor=agent,
        check_no=2,
        outcome=VerdictOutcome.FAILED,
        evidence=(
            "`query=priority > high` отвечает `search_operator_not_supported`, но "
            "`details.allowed` пуст: список операторов собирается только для текстовых полей"
        ),
    )
    await case_service.add_summary(
        session,
        task,
        actor=agent,
        done="Первая проверка пройдена, вторая провалена: список операторов приходит пустым",
        remaining="Собрать список операторов для сравнимых полей и перепроверить проверку 2",
        blockers="Задача блокера ещё не закрыта",
        next_step="Дособрать `details.allowed` в подборе операторов и подшить новый вердикт",
    )
    await links_service.add_link(session, task, blocker, actor=agent, kind=LinkKind.BLOCKED_BY)
    return task


async def _cancelled_task(session: AsyncSession, project: Project, *, agent: Actor) -> Task:
    """Отменённая задача: закрыта без результата, причина обязательна."""
    task = await tasks_service.create_task(
        session,
        actor=agent,
        project=project,
        area=DEMO_AREA,
        title="Добавить вебхуки на закрытие задачи",
        description="Назначателю нужен push вместо чтения ленты.",
        goal="Назначатель узнаёт о закрытии задачи без опроса",
        context="Лента уже умеет долгое ожидание на `LISTEN/NOTIFY`",
        constraints="Доставка гарантированной быть не может: получатель бывает недоступен",
        output="Реестр подписок и отправка с повторами",
        checks=["Закрытие задачи доставляется подписчику"],
    )
    await tasks_service.transition_task(
        session,
        task,
        actor=agent,
        to=TaskStatus.CANCELLED,
        reason="Лента с ожиданием закрывает ту же потребность; вебхуки отвергнуты концепцией",
    )
    return task


async def _discussions(
    session: AsyncSession,
    project: Project,
    *,
    agent: Actor,
    owner: Actor,
    human: Participant,
    deferred: Task,
) -> None:
    """Три обсуждения (решение `TRK#51`): закрытое, ждущее человека и ждущее агента.

    Заводятся последними, после всех задач, — ключи задач от этого не сдвигаются. Признаков
    и дел задач, которые читают сквозные сценарии интерфейса, обсуждения не трогают: вопрос
    открытого обсуждения считается вопросом привязанной задачи (`TRK#51`, п. 4), а запись
    привязки ложится в её дело, и у DEMO-4 стало бы два вопроса, у DEMO-6 — на две записи
    больше. Поэтому открытые обсуждения — без задач, а привязка и отвязка закрытого — у
    отложенной DEMO-9, чьего дела сценарии не считают; после отвязки её ничто не держит.
    """
    # Закрытое: вопрос, ответ, итог и `closed`; задача привязана и отвязана.
    settled = await discussions_service.create_discussion(
        session,
        actor=agent,
        project=project,
        title="Показывать ли во входящей вопросы архивных проектов?",
        opening=EntryType.QUESTION,
        body="Ответить на них нельзя, пока проект в архиве; показывать — значит звать в тупик.",
        addressees=[human.name],
        tasks=[deferred],
    )
    question_no = 2  # `created` — первая запись дела, вопрос, которым оно заведено, — вторая
    answer = await case_service.append_discussion_entry(
        session,
        settled,
        actor=owner,
        type=EntryType.ANSWER,
        body="Не показывать. Вернётся проект из архива — вернутся и вопросы.",
        payload={"question_no": question_no},
    )
    await discussions_service.detach_task(session, settled, deferred, actor=agent)
    await discussions_service.close_discussion(
        session,
        settled,
        actor=agent,
        decided=(
            f"Вопросы архивных проектов во входящей не показываются ({settled.address}#{answer.no})"
        ),
        superseded="ничего",
        open="ничего",
        refs=[f"{settled.address}#{answer.no}"],
    )

    # Ждёт человека: вопрос без ответа — входящая по обсуждениям. Без задач: обсуждение
    # без привязок бывает, и находят его отбором `turn`, а не через задачу.
    await discussions_service.create_discussion(
        session,
        actor=agent,
        project=project,
        title="Сколько хранить дела отменённых задач?",
        opening=EntryType.QUESTION,
        body="Концепция говорит «записи постоянны»; менять её может только владелец.",
        addressees=[human.name],
    )

    # Ждёт агента: человек завёл обсуждение запиской, без задач.
    await discussions_service.create_discussion(
        session,
        actor=owner,
        project=project,
        title="Нужна ли ночная тема для демо-записи?",
        opening=EntryType.NOTE,
        body="Посмотрел запись в тёмной теме — читается хуже. Подумайте, что с этим делать.",
    )


async def _moved_there_and_back(
    session: AsyncSession, task: Task, *, home: Project, owner: Actor
) -> None:
    """Перенос в соседний проект и возврат (`CONCEPT.md`, 3.3): две записи `moved`.

    Задача возвращается со своим ключом, а не с новым номером, и прежний ключ соседнего
    проекта остаётся в `previous_keys` — на экране видно оба правила сразу. Переносит
    владелец: перенос — действие владельца. Соседний проект после возврата пуст и
    уходит в архив с причиной — так, как опустевший проект архивирует агент, а не трекер.
    """
    neighbour = await projects_service.create_project(
        session,
        actor=owner,
        key=DEMO_NEIGHBOUR_KEY,
        title="Прежний проект",
        description="Проект, откуда задачи переехали в DEMO.",
    )
    await areas_service.create_area(
        session, actor=owner, address=_NEIGHBOUR_AREA, title="Прошлое", description=""
    )
    await tasks_service.move_task(
        session,
        task,
        actor=owner,
        project=neighbour,
        reason="Вебхуки — тема интеграций, а она ведётся в отдельном проекте",
        area=_NEIGHBOUR_AREA,
    )
    await tasks_service.move_task(
        session,
        task,
        actor=owner,
        project=home,
        reason="Интеграции снова ведутся в DEMO: отдельный проект не прижился",
        area=DEMO_AREA,
    )
    await projects_service.archive_project(
        session, neighbour, actor=owner, reason="Задачи вернулись в DEMO, проект пуст"
    )
