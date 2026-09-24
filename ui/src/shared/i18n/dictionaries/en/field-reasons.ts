/**
 * Texts for a single field's reason: the backend's `details.fields[].reason`
 * (`app/domain/fields.py`). The reason is a `snake_case` code, part of the contract
 * like `error.code`, but the backend does not ship a full catalogue of them: they are
 * internal strings from domain normalizers scattered across `app/domain/tasks.py`,
 * `app/domain/case.py` and `app/services/case.py`, not a closed enum.
 *
 * Unlike `errors.ts`, this dictionary is therefore not required to cover every reason
 * — nothing checks it for completeness. A reason missing here falls back to a generic
 * text naming the code itself (`fieldReasonText`, `shared/errors/text.ts`) instead of
 * breaking the screen.
 */
export const fieldReasons = {
  conflicts_with: 'Cannot be combined with another change in the same request.',
  empty_item: 'The list has an empty value.',
  malformed_entry_ref: 'The entry reference cannot be parsed.',
  malformed_task_key: 'The task key cannot be parsed.',
  multiline_not_allowed: 'Line breaks are not allowed here.',
  no_checks: 'The task has no review checks at all.',
  no_such_check: 'There is no check with that number.',
  not_a_boolean: 'A yes/no value was expected.',
  not_a_list: 'A list was expected.',
  not_a_question: 'The entry with that number is not a question.',
  not_a_remark: 'The entry with that number is not a remark.',
  not_a_string: 'A string was expected.',
  not_allowed: 'This value is not allowed.',
  not_an_integer: 'A whole number was expected.',
  out_of_range: 'The value is outside the allowed range.',
  required: 'This field is required.',
  service_type: 'Only the tracker itself files this kind of entry, not an agent.',
  too_long: 'This value is too long.',
  too_many: 'There are more items than allowed.',
  unknown_entry: 'There is no entry with that number.',
  unknown_participant: 'There is no participant by that name in the registry.',
  unknown_task: 'There is no task with that key.',
} as const;
