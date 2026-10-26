import { useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { discussionKeys } from '@/entities/discussion';
import { sessionKeys } from '@/entities/session';
import { apiClient, unwrap, unwrapEmpty, type components } from '@/shared/api';

type Entry = components['schemas']['EntryRead'];

/**
 * Что устаревает от записи или привязки: само обсуждение (карточка, лента, тела записей),
 * все списки обсуждений (входящая, история, блок в карточке задачи) и число во входящей.
 * Пересчитывает всё это бэкенд: интерфейс только просит перечитать (TRK#244) —
 * «чей ход» и «вопросов без ответа» считаются из дела, и дописать их «по ответу» значило
 * бы однажды показать не то, что там на самом деле.
 */
function refresh(queryClient: QueryClient, address: string, taskKey?: string): void {
  void queryClient.invalidateQueries({ queryKey: discussionKeys.detail(address) });
  void queryClient.invalidateQueries({ queryKey: discussionKeys.all });
  void queryClient.invalidateQueries({ queryKey: sessionKeys.bootstrap });
  // Привязка и ответ меняют и задачу: запись `attached`/`detached` ложится в её дело,
  // а признаки ожидания считаются из вопросов её обсуждений.
  if (taskKey !== undefined) void queryClient.invalidateQueries({ queryKey: ['task', taskKey] });
}

export interface ReplyInput {
  address: string;
  questionNo: number;
  body: string;
  /** Метка выбранного варианта вопроса; без неё ответ — один свободный текст. */
  choice?: string;
  /** Ключ повтора: тот же на каждой попытке отправить этот ответ. */
  idempotencyKey: string;
  /** Id загруженных файлов, прикреплённых к ответу. */
  files?: string[];
}

/** Ответ человека на вопрос обсуждения (`TRK#51`, п. 8, форма «Ответить на #N»). */
export function useReply() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      address,
      questionNo,
      body,
      choice,
      idempotencyKey,
      files,
    }: ReplyInput): Promise<Entry> =>
      unwrap(
        apiClient.POST('/api/v1/discussions/{discussion}/entries', {
          params: { path: { discussion: address }, header: { 'Idempotency-Key': idempotencyKey } },
          body: {
            type: 'answer',
            body,
            payload: {
              question_no: questionNo,
              ...(choice === undefined ? {} : { choice }),
            },
            ...(files === undefined || files.length === 0 ? {} : { files }),
          },
        }),
      ),
    onSuccess: (_entry, { address }) => refresh(queryClient, address),
  });
}

export interface NoteInput {
  address: string;
  title: string;
  body: string;
  idempotencyKey: string;
  files?: string[];
}

/** Свободная заметка человека в обсуждение: задаёт работу привязанных задач, как ответ. */
export function useNote() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ address, title, body, idempotencyKey, files }: NoteInput): Promise<Entry> =>
      unwrap(
        apiClient.POST('/api/v1/discussions/{discussion}/entries', {
          params: { path: { discussion: address }, header: { 'Idempotency-Key': idempotencyKey } },
          body: {
            type: 'note',
            title,
            body,
            ...(files === undefined || files.length === 0 ? {} : { files }),
          },
        }),
      ),
    onSuccess: (_entry, { address }) => refresh(queryClient, address),
  });
}

/** Привязать задачу: она зависит от итога обсуждения (`TRK#51`, п. 3). */
export function useAttachTask(address: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ task, idempotencyKey }: { task: string; idempotencyKey: string }) =>
      unwrap(
        apiClient.POST('/api/v1/discussions/{discussion}/tasks', {
          params: { path: { discussion: address }, header: { 'Idempotency-Key': idempotencyKey } },
          body: { task },
        }),
      ),
    onSuccess: (attached) => refresh(queryClient, address, attached.key),
  });
}

/** Отвязать задачу: итог её больше не держит. */
export function useDetachTask(address: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ task }: { task: string }): Promise<void> =>
      unwrapEmpty(
        apiClient.DELETE('/api/v1/discussions/{discussion}/tasks/{task_key}', {
          params: { path: { discussion: address, task_key: task } },
        }),
      ),
    onSuccess: (_none, { task }) => refresh(queryClient, address, task),
  });
}

export interface CreateDiscussionInput {
  project: string;
  title: string;
  body: string;
  tasks: string[];
  idempotencyKey: string;
}

/** Новое обсуждение запиской, без вопроса, с привязкой задач тем же действием. */
export function useCreateDiscussion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ project, title, body, tasks, idempotencyKey }: CreateDiscussionInput) =>
      unwrap(
        apiClient.POST('/api/v1/discussions', {
          params: { header: { 'Idempotency-Key': idempotencyKey } },
          body: { project, title, body, tasks },
        }),
      ),
    onSuccess: (discussion) => {
      void queryClient.invalidateQueries({ queryKey: discussionKeys.all });
      void queryClient.invalidateQueries({ queryKey: sessionKeys.bootstrap });
      for (const task of discussion.tasks) {
        void queryClient.invalidateQueries({ queryKey: ['task', task.key] });
      }
    },
  });
}
