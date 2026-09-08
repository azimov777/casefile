"""Демо-данные: установка, на которой видно каждый экран.

Зачем это в `services`, а не скриптом рядом с репозиторием: демо обязано проходить теми
же сценариями, что и живая работа. Скрипт, пишущий в таблицы напрямую, наполнил бы базу
задачами без служебных записей дела, без номеров записей и без ленты — то есть данными,
которых трекер породить не может, и первый же экран показал бы то, чего в жизни не
бывает.

Что наполняется (`docs/tasks`, задача 29):

- очередь `DEMO` с описанием — общим контекстом всех её задач;
- семь задач: все шесть статусов, `in_progress` — двумя, потому что интересны обе:
  с живой сводкой и с провальным вердиктом, держащим выход в `done`;
- записи **всех** типов, включая служебные `section_changed`, `assignee_changed`,
  `link_added` и `link_removed`: экран дела иначе показывал бы половину словаря;
- открытый блокирующий вопрос, адресованный человеку, — «входящая» и первый экран
  без него пусты;
- связи всех трёх видов;
- три автора: человек, постоянный агент и временный агент, подписанный меткой.

## Идемпотентность

Признак «демо уже наполнено» — существование очереди `DEMO`. Повтор ничего не делает и
говорит об этом. Считать задачи или записи и дописывать недостающее было бы хуже: демо
— это одна связная история, и наполовину доигранная история хуже, чем отсутствующая.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.participant import Participant
from app.db.models.queue import Queue
from app.db.models.task import Task
from app.db.repositories import ParticipantRepository, QueueRepository
from app.domain.authors import label_author
from app.domain.case import EntryType, RemarkOutcome, VerdictOutcome
from app.domain.links import LinkKind
from app.domain.participants import ParticipantKind
from app.domain.queues import normalize_queue_key
from app.domain.tasks import TaskPriority, TaskStatus
from app.domain.tokens import TokenScope
from app.services import case as case_service
from app.services import links as links_service
from app.services import participants as participants_service
from app.services import queues as queues_service
from app.services import tasks as tasks_service
from app.services.auth import TRACKER_ACTOR, Actor
from app.services.setup import DEFAULT_OWNER_NAME
from app.services.tasks import TaskChanges

#: Ключ демонстрационной очереди. Он же признак «демо уже наполнено».
DEMO_QUEUE_KEY = "DEMO"

#: Постоянный агент демо: ему адресуемы вопросы и он подписывает большую часть записей.
DEMO_AGENT_NAME = "demo_agent"

#: Метка временного агента: у него нет строки в реестре, подпись приезжает заголовком
#: `X-Actor-Label`. В демо он есть затем, чтобы на экране дела было видно обе формы
#: identity агента (`CONCEPT.md`, 3.1), а не только именную.
DEMO_LABEL = "nightly_agent"

_QUEUE_DESCRIPTION = """Демонстрационная очередь: на ней видно каждый экран интерфейса.

Задачи здесь ненастоящие, но собраны настоящими сценариями трекера — теми же, которыми
работают агенты. Дело каждой задачи читается сверху вниз как история: что решили, что
пробовали, что выяснили, о чём спросили.

- Код: этого проекта не существует, ссылки в записях — примеры формы, а не адреса.
- Кандидат для назначателя здесь ровно один: `status: open and blocked: false and
  open_blocking_questions: 0`.
"""


@dataclass(frozen=True, slots=True)
class DemoData:
    """Что наполнено. `None` в `queue` означает «уже было наполнено, ничего не делали»."""

    queue: Queue | None
    tasks: list[Task]

    @property
    def created(self) -> bool:
        return self.queue is not None


async def seed_demo(session: AsyncSession) -> DemoData:
    """Наполняет установку демонстрационными данными. Повтор ничего не делает.

    Автор каждого действия — тот, кто делал бы его в жизни: задачи ведёт агент, отвечает
    на вопросы человек, очередь и участников заводит владелец установки. Подставлять
    везде одного автора было бы проще, но экран дела перестал бы показывать то, ради
    чего в записи есть подпись.
    """
    key = normalize_queue_key(DEMO_QUEUE_KEY)
    if await QueueRepository(session).get_by_key(key) is not None:
        return DemoData(queue=None, tasks=[])

    human = await _human(session)
    owner = Actor(author=human.author, scope=TokenScope.MAIN, participant=human)
    robot = await _agent(session, owner)
    agent = Actor(author=robot.author, scope=TokenScope.TASK, participant=robot)
    # Временный агент: участника за ним нет, подпись — метка. Набор `task`, как у
    # общего агентского токена, которым такой агент и ходит.
    temporary = Actor(author=label_author(DEMO_LABEL), scope=TokenScope.TASK)

    queue = await queues_service.create_queue(
        session,
        actor=owner,
        key=DEMO_QUEUE_KEY,
        title="Демонстрация",
        description=_QUEUE_DESCRIPTION,
    )

    done = await _done_task(session, queue, agent=agent, temporary=temporary, human=human)
    in_progress = await _in_progress_task(session, queue, agent=agent, owner=owner, human=human)
    candidate = await _candidate_task(session, queue, agent=agent)
    waiting = await _waiting_task(session, queue, agent=agent, human=human)
    child = await _child_task(session, queue, agent=agent, parent=in_progress)
    checking = await _checking_task(session, queue, agent=agent, blocker=in_progress)
    cancelled = await _cancelled_task(session, queue, agent=agent)

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
    await links_service.add_link(session, candidate, waiting, actor=agent, kind=LinkKind.RELATES)

    return DemoData(
        queue=queue,
        tasks=[done, in_progress, candidate, waiting, child, checking, cancelled],
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
        description="Агент демонстрационной очереди: ведёт её задачи",
    )


# --- Задачи ---------------------------------------------------------------------------


async def _done_task(
    session: AsyncSession,
    queue: Queue,
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
        queue=queue,
        title="Ключ задачи сгорает на отклонённом запросе",
        description=(
            "Номер выдаётся счётчиком очереди до валидации тела, поэтому запрос, "
            "отклонённый по форме, тратит номер навсегда."
        ),
        goal="Отклонённый запрос не тратит номер очереди",
        context="Номер выдаёт `queues.next_task_number`, вызов стоит первым в сценарии",
        constraints="Счётчик очереди не переписывать: номера не переиспользуются",
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
            goal="Отклонённый запрос не тратит номер очереди ни при какой ошибке валидации"
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
        title="Соседняя очередь заводит задачи тем же путём, её это тоже чинит",
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
    await case_service.add_verdict(
        session,
        task,
        actor=agent,
        check_no=1,
        outcome=VerdictOutcome.PASSED,
        evidence="Создание без названия отвечает 422, `last_task_number` остался 7",
    )
    # Вердикт человека: обзорные проверки закрывает не только тот, кто вёл задачу.
    await case_service.add_verdict(
        session,
        task,
        actor=Actor(author=human.author, scope=TokenScope.TASK, participant=human),
        check_no=2,
        outcome=VerdictOutcome.PASSED,
        evidence="`docker compose run --rm test` — 214 passed",
    )
    await tasks_service.transition_task(session, task, actor=agent, to=TaskStatus.DONE)
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
    reader = Actor(author=human.author, scope=TokenScope.TASK, participant=human)
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
    queue: Queue,
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
        queue=queue,
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


async def _candidate_task(session: AsyncSession, queue: Queue, *, agent: Actor) -> Task:
    """Свободная задача без блокеров и открытых вопросов — кандидат назначателя."""
    task = await tasks_service.create_task(
        session,
        actor=agent,
        queue=queue,
        title="Описание очереди не показывается в карточке задачи",
        description="Агент получает ключ и название очереди, а описание запрашивает отдельно.",
        goal="Понятно, откуда брать общий контекст очереди",
        context="`get_queue` отдаёт описание целиком; в карточке задачи его нет намеренно",
        constraints="Описание в карточку задачи не добавлять: оно длинное и съест контекст",
        output="Строка в тексте скила о том, когда звать `get_queue`",
        checks=["Скил называет `get_queue` в разделе о начале работы"],
        priority=TaskPriority.LOW,
    )
    await tasks_service.transition_task(session, task, actor=agent, to=TaskStatus.OPEN)
    return task


async def _waiting_task(
    session: AsyncSession, queue: Queue, *, agent: Actor, human: Participant
) -> Task:
    """Задача в `waiting`: сценарий `CONCEPT.md`, 4.6, строка «Ответа, долго».

    Агент упёрся в вопрос, на который сам ответить не может, задал его с признаком
    `blocking`, написал сводку и ушёл в `waiting`. Ход за человеком, поэтому не в `open`:
    в `open` стоит то, что можно брать. Человек видит вопрос в своей «входящей», а саму
    задачу — отбором `status: waiting`.
    """
    task = await tasks_service.create_task(
        session,
        actor=agent,
        queue=queue,
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
    await case_service.ask(
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
        to=TaskStatus.WAITING,
        reason="Жду ответа владельца на вопрос о сроке хранения дел отменённых задач",
    )
    return task


async def _child_task(session: AsyncSession, queue: Queue, *, agent: Actor, parent: Task) -> Task:
    """Ребёнок задачи в работе: декомпозиция, ещё не открытая к работе.

    Разделы намеренно заполнены не все: задача в `backlog` — это черновик, и экран
    должен показывать, что до `open` её ещё дописывают.
    """
    task = await tasks_service.create_task(
        session,
        actor=agent,
        queue=queue,
        title="Тест на разрыв потока посреди выдачи",
        description="Отдельная задача: тест требует своего стенда с обрывом соединения.",
        goal="Разрыв потока покрыт тестом",
        context="Родительская задача нашла причину; тест выделен, чтобы не смешивать правки",
    )
    await links_service.add_link(session, task, parent, actor=agent, kind=LinkKind.PARENT)
    return task


async def _checking_task(
    session: AsyncSession, queue: Queue, *, agent: Actor, blocker: Task
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
        queue=queue,
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
    await tasks_service.transition_task(session, task, actor=agent, to=TaskStatus.IN_PROGRESS)
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


async def _cancelled_task(session: AsyncSession, queue: Queue, *, agent: Actor) -> Task:
    """Отменённая задача: закрыта без результата, причина обязательна."""
    task = await tasks_service.create_task(
        session,
        actor=agent,
        queue=queue,
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
