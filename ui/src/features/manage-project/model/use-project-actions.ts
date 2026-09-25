import { useMutation, useQueryClient } from '@tanstack/react-query';
import { questionKeys, remarkKeys } from '@/entities/entry';
import { projectKeys } from '@/entities/project';
import { sessionKeys } from '@/entities/session';
import { useOnceKey } from '@/shared/lib';
import {
  archiveProject,
  createProject,
  restoreProject,
  fileNote,
  removeAttribute,
  setAttribute,
  updateProject,
  type ArchivingInput,
  type CreateProjectInput,
  type NoteInput,
  type RemoveAttributeInput,
  type SetAttributeInput,
} from '../api/projects';

type Input<TInput> = Omit<TInput, 'idempotencyKey'>;

/*
 * Действия с проектом (`UI-175`). После каждого интерфейс только просит бэкенд
 * перечитать то, что изменилось, и не правит кэш руками: порядок атрибутов, номер
 * записи и подпись автора считает бэкенд (`docs/CONCEPT.md`, 6).
 *
 * Префикс `['project', key]` накрывает карточку, дело проекта и тела его записей
 * (`projectKeys`), `bootstrap` — список проектов в панели. Живой поток кадры проекта
 * пока отбрасывает (`UI-177`), поэтому перечитывание здесь — единственный путь, каким
 * своё действие доезжает до экрана.
 */

/** Заводит проект: он обязан появиться в панели сразу, а не после перезагрузки. */
export function useCreateProject() {
  const queryClient = useQueryClient();
  const once = useOnceKey<Input<CreateProjectInput>>();

  return useMutation({
    mutationFn: (input: Input<CreateProjectInput>) =>
      createProject({ ...input, idempotencyKey: once.keyFor(input) }),
    onSuccess: () => {
      once.forget();
      void queryClient.invalidateQueries({ queryKey: sessionKeys.bootstrap });
    },
  });
}

/** Правит название и описание: название стоит и в панели, поэтому и `bootstrap`. */
export function useUpdateProject() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: updateProject,
    onSuccess: (_project, { key }) => {
      void queryClient.invalidateQueries({ queryKey: projectKeys.detail(key) });
      void queryClient.invalidateQueries({ queryKey: sessionKeys.bootstrap });
    },
  });
}

/** Заводит или меняет атрибут: новое значение и запись в деле проекта. */
export function useSetAttribute() {
  const queryClient = useQueryClient();
  const once = useOnceKey<Input<SetAttributeInput>>();

  return useMutation({
    mutationFn: (input: Input<SetAttributeInput>) =>
      setAttribute({ ...input, idempotencyKey: once.keyFor(input) }),
    onSuccess: (_attribute, { projectKey }) => {
      once.forget();
      void queryClient.invalidateQueries({ queryKey: projectKeys.detail(projectKey) });
    },
  });
}

/** Снимает атрибут с причиной. */
export function useRemoveAttribute() {
  const queryClient = useQueryClient();
  const once = useOnceKey<Input<RemoveAttributeInput>>();

  return useMutation({
    mutationFn: (input: Input<RemoveAttributeInput>) =>
      removeAttribute({ ...input, idempotencyKey: once.keyFor(input) }),
    onSuccess: (_entry, { projectKey }) => {
      once.forget();
      void queryClient.invalidateQueries({ queryKey: projectKeys.detail(projectKey) });
    },
  });
}

/**
 * Заметка в дело проекта. Ключ повтора приходит из черновика формы (`Composer`), как у
 * замечания: он переживает и провал попытки, и перезагрузку вкладки.
 */
export function useFileNote() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: NoteInput) => fileNote(input),
    onSuccess: (_entry, { projectKey }) => {
      void queryClient.invalidateQueries({ queryKey: projectKeys.detail(projectKey) });
    },
  });
}

/**
 * Архив и восстановление (`UI-176`). Меняется не только карточка: архивный проект
 * бэкенд прячет из панели, из поиска задач и из входящей со счётчиком (TRK-160), —
 * поэтому перечитываются и первый кадр, и списки задач, вопросов и замечаний. Что
 * именно в них попадёт, решает бэкенд, а не интерфейс.
 */
function useArchiving(mutationFn: (input: ArchivingInput) => Promise<unknown>) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn,
    onSuccess: (_project, { key }) => {
      for (const queryKey of [
        projectKeys.detail(key),
        sessionKeys.bootstrap,
        ['tasks'],
        questionKeys.all,
        remarkKeys.all,
      ]) {
        void queryClient.invalidateQueries({ queryKey });
      }
    },
  });
}

export function useArchiveProject() {
  return useArchiving(archiveProject);
}

export function useRestoreProject() {
  return useArchiving(restoreProject);
}
