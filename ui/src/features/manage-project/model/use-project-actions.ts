import { useMutation, useQueryClient, type QueryKey } from '@tanstack/react-query';
import { areaKeys } from '@/entities/area';
import { questionKeys, remarkKeys } from '@/entities/entry';
import { projectKeys } from '@/entities/project';
import { sessionKeys } from '@/entities/session';
import { splitAreaAddress, useOnceKey } from '@/shared/lib';
import {
  archiveArea,
  archiveProject,
  createArea,
  createProject,
  fileEntry,
  removeAttribute,
  restoreArea,
  restoreProject,
  setAttribute,
  updateArea,
  updateProject,
  type ArchivingInput,
  type CreateAreaInput,
  type CreateProjectInput,
  type AreaArchivingInput,
  type EntryInput,
  type Holder,
  type RemoveAttributeInput,
  type SetAttributeInput,
  type UpdateAreaInput,
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
 * и тела записей проекта — `['project', key]`, области — `['area', адрес]`.
 */
function holderKey(holder: Holder): QueryKey {
  return holder.kind === 'area' ? areaKeys.detail(holder.key) : projectKeys.detail(holder.key);
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

/** Заводит или меняет атрибут: новое значение и запись в деле проекта или области. */
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
 * Запись человека в дело проекта или области. Ключ повтора приходит из черновика
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
 * Действия с областью (TRK-557). Список областей живёт под префиксом проекта
 * (`areaKeys.list`), поэтому заведение, правка и архив перечитывают проект целиком —
 * его карточку с активными областями и раздел «Области». Правка и архив меняют
 * ещё и то, что об области знает каждая её задача: название и признак архива едут в
 * пакете карточки (`['task']`) и в строке выдачи (`['tasks']`). Какие задачи затронуты,
 * интерфейс не вычисляет — перечитывается всё прочитанное, а бэкенд отвечает как есть.
 */

/** Заводит область; ключ повтора окна переживает провал попытки. */
export function useCreateArea() {
  const queryClient = useQueryClient();
  const once = useOnceKey<Input<CreateAreaInput>>();

  return useMutation({
    mutationFn: (input: Input<CreateAreaInput>) =>
      createArea({ ...input, idempotencyKey: once.keyFor(input) }),
    onSuccess: (_area, { projectKey }) => {
      once.forget();
      void queryClient.invalidateQueries({ queryKey: projectKeys.detail(projectKey) });
    },
  });
}

/** Что перечитать после правки или архива области — см. комментарий выше. */
function areaChanged(address: string): QueryKey[] {
  return [
    areaKeys.detail(address),
    projectKeys.detail(splitAreaAddress(address).projectKey),
    ['task'],
    ['tasks'],
  ];
}

export function useUpdateArea() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: UpdateAreaInput) => updateArea(input),
    onSuccess: (_area, { address }) => {
      for (const queryKey of areaChanged(address)) {
        void queryClient.invalidateQueries({ queryKey });
      }
    },
  });
}

function useAreaArchiving(mutationFn: (input: AreaArchivingInput) => Promise<unknown>) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn,
    onSuccess: (_area, { address }) => {
      for (const queryKey of areaChanged(address)) {
        void queryClient.invalidateQueries({ queryKey });
      }
    },
  });
}

export function useArchiveArea() {
  return useAreaArchiving(archiveArea);
}

export function useRestoreArea() {
  return useAreaArchiving(restoreArea);
}
