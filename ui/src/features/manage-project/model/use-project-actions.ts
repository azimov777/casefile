import { useMutation, useQueryClient, type QueryKey } from '@tanstack/react-query';
import { directionKeys } from '@/entities/direction';
import { questionKeys, remarkKeys } from '@/entities/entry';
import { projectKeys } from '@/entities/project';
import { sessionKeys } from '@/entities/session';
import { splitDirectionAddress, useOnceKey } from '@/shared/lib';
import {
  archiveDirection,
  archiveProject,
  createDirection,
  createProject,
  fileEntry,
  removeAttribute,
  restoreDirection,
  restoreProject,
  setAttribute,
  updateDirection,
  updateProject,
  type ArchivingInput,
  type CreateDirectionInput,
  type CreateProjectInput,
  type DirectionArchivingInput,
  type EntryInput,
  type Holder,
  type RemoveAttributeInput,
  type SetAttributeInput,
  type UpdateDirectionInput,
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

/**
 * Префикс того, что устарело от атрибута или записи в деле: карточка с атрибутами, дело
 * и тела записей проекта — `['project', key]`, направления — `['direction', адрес]`.
 */
function holderKey(holder: Holder): QueryKey {
  return holder.kind === 'direction'
    ? directionKeys.detail(holder.key)
    : projectKeys.detail(holder.key);
}

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

/** Заводит или меняет атрибут: новое значение и запись в деле проекта или направления. */
export function useSetAttribute() {
  const queryClient = useQueryClient();
  const once = useOnceKey<Input<SetAttributeInput>>();

  return useMutation({
    mutationFn: (input: Input<SetAttributeInput>) =>
      setAttribute({ ...input, idempotencyKey: once.keyFor(input) }),
    onSuccess: (_attribute, { holder }) => {
      once.forget();
      void queryClient.invalidateQueries({ queryKey: holderKey(holder) });
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
    onSuccess: (_entry, { holder }) => {
      once.forget();
      void queryClient.invalidateQueries({ queryKey: holderKey(holder) });
    },
  });
}

/**
 * Запись человека в дело проекта или направления. Ключ повтора приходит из черновика
 * формы (`Composer`), как у замечания: он переживает и провал попытки, и перезагрузку
 * вкладки.
 */
export function useFileEntry() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: EntryInput) => fileEntry(input),
    onSuccess: (_entry, { holder }) => {
      void queryClient.invalidateQueries({ queryKey: holderKey(holder) });
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

/*
 * Действия с направлением (TRK-557). Список направлений живёт под префиксом проекта
 * (`directionKeys.list`), поэтому заведение, правка и архив перечитывают проект целиком —
 * его карточку с активными направлениями и раздел «Направления». Правка и архив меняют
 * ещё и то, что о направлении знает каждая его задача: название и признак архива едут в
 * пакете карточки (`['task']`) и в строке выдачи (`['tasks']`). Какие задачи затронуты,
 * интерфейс не вычисляет — перечитывается всё прочитанное, а бэкенд отвечает как есть.
 */

/** Заводит направление; ключ повтора окна переживает провал попытки. */
export function useCreateDirection() {
  const queryClient = useQueryClient();
  const once = useOnceKey<Input<CreateDirectionInput>>();

  return useMutation({
    mutationFn: (input: Input<CreateDirectionInput>) =>
      createDirection({ ...input, idempotencyKey: once.keyFor(input) }),
    onSuccess: (_direction, { projectKey }) => {
      once.forget();
      void queryClient.invalidateQueries({ queryKey: projectKeys.detail(projectKey) });
    },
  });
}

/** Что перечитать после правки или архива направления — см. комментарий выше. */
function directionChanged(address: string): QueryKey[] {
  return [
    directionKeys.detail(address),
    projectKeys.detail(splitDirectionAddress(address).projectKey),
    ['task'],
    ['tasks'],
  ];
}

export function useUpdateDirection() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: UpdateDirectionInput) => updateDirection(input),
    onSuccess: (_direction, { address }) => {
      for (const queryKey of directionChanged(address)) {
        void queryClient.invalidateQueries({ queryKey });
      }
    },
  });
}

function useDirectionArchiving(mutationFn: (input: DirectionArchivingInput) => Promise<unknown>) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn,
    onSuccess: (_direction, { address }) => {
      for (const queryKey of directionChanged(address)) {
        void queryClient.invalidateQueries({ queryKey });
      }
    },
  });
}

export function useArchiveDirection() {
  return useDirectionArchiving(archiveDirection);
}

export function useRestoreDirection() {
  return useDirectionArchiving(restoreDirection);
}
