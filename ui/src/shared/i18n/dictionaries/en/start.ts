/**
 * Экран «Начало» (`TRK-361`): что такое Casefile, откуда берутся задачи, что сказать
 * агенту и что делает человек — четыре вопроса в порядке решения `TRK-360#14`.
 *
 * Тексты трёх фраз (`phrases.*.text`) скопированы символ в символ из раздела «Контекст»
 * задачи `TRK-361` (источник — `app/domain/tutorial.py`): их сверяет отдельная проверка
 * копий, и здесь их нельзя поправить «для красоты» или перефразировать.
 *
 * Тексты `sections.why.body` и `sections.source.body` — тем же приёмом, но из «Контекста»
 * задачи `TRK-378` (замечание координатора в деле `TRK-361#37`: прежние тексты отвечали
 * не на «зачем», а перечисляли, чем трекер не является): их тоже сверяет отдельная
 * проверка, и здесь их нельзя поправить «для красоты» или перефразировать.
 */
export const start = {
  steps: {
    label: 'First steps',
    done: 'Done',
    connect: {
      title: 'Connect the agent',
    },
    tellAgent: {
      title: 'Tell the agent where to start',
    },
    watch: {
      title: 'Watch and answer here',
    },
  },
  sections: {
    why: {
      title: 'What this is for',
      body: 'AI agents forget everything between sessions: the next one starts from scratch, re-reads the code and retries what already failed. Casefile gives every task a case file — a log of decisions, attempts, findings and questions. The next agent reads the case and picks up exactly where the last one stopped. You watch on the board what every agent is doing, and answer their questions.',
    },
    source: {
      title: 'Where tasks come from',
      body: 'Agents create and carry the tasks — at your request, in their own chat. There is no “create task” button here on purpose: you tell the agent what you need, and it splits the work into tasks.',
    },
    tellAgent: {
      title: 'What to tell the agent',
      intro:
        'Copy a phrase and send it to the agent in chat — from there it works with Casefile on its own.',
      // Между второй и третьей фразой (TRK-360#40): почему это новая сессия и как
      // выбирать модели — без имён клиентов и моделей (TRK-361, «Что важно»).
      newSession:
        'Say the next one in a new agent session: it starts with a clean context and knows only what the task cases record. File tasks with a stronger model; carry them out with cheaper ones, one task per agent.',
    },
    you: {
      title: 'What you do yourself',
      body: 'Watch where things stand, answer the questions an agent addresses to you, leave a “this came out wrong” remark where work missed the mark, and run your own projects.',
    },
  },
  phrases: {
    tutorial: {
      title: 'Introduction',
      lead: 'Walk through the tutorial task with the agent — it shows the way of working live.',
      label: 'Introduction phrase',
      caption: 'Send to the agent in chat',
      text: 'Take the tutorial task START-1 in Casefile and walk me through it.',
    },
    file: {
      title: 'File tasks',
      lead: 'Describe your work — the agent breaks it into tracker tasks.',
      label: 'File tasks phrase',
      caption: 'Send to the agent in chat',
      text: "File tasks in Casefile for my work: a project for it if there is none yet, and tasks with all their sections and checks, each small enough for one agent to finish in one go, each naming its environment in `context` — where the work lives and how to run its checks. Don't start the work itself; if I haven't described it yet, ask me.",
    },
    execute: {
      title: 'Carry out tasks',
      label: 'Carry out tasks phrase',
      caption: 'Send to the agent in chat',
      text: 'Carry out the tasks for this work from the Casefile tracker. Hand them to agents, one task per agent, to save your own context, and give them cheaper models where those cope.',
    },
  },
  actions: {
    skip: 'Skip',
    complete: 'Got it',
  },
} as const;
