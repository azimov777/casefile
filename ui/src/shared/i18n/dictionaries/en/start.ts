/**
 * Экран «Начало» (`TRK-361`): что такое Casefile, откуда берутся задачи, что сказать
 * агенту и что делает человек — четыре вопроса в порядке решения `TRK-360#14`.
 *
 * Тексты трёх фраз (`phrases.*.text`) скопированы символ в символ из раздела «Контекст»
 * задачи `TRK-361` (источник — `app/domain/tutorial.py`): их сверяет отдельная проверка
 * копий, и здесь их нельзя поправить «для красоты» или перефразировать.
 */
export const start = {
  sections: {
    why: {
      title: 'What this is for',
      body: 'Casefile stores tasks and a case for each one — a record of what was done and why. Agents file and carry tasks through MCP; the tracker itself never decides or acts on its own, neither on a schedule nor in the agent’s place. This is not a task manager for a person: it is a log of what agents do.',
    },
    source: {
      title: 'Where tasks come from',
      body: 'Agents file and carry out tasks by themselves — there is no “create task” button here. A person looks at where things stand, rather than writing up assignments.',
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
