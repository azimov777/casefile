/**
 * The «Files» screen (TRK-739, the owner's word TRK~8#4): every file of the installation
 * in one list. Search by name, sort, filter by type and project; open, upload, replace and
 * delete — one file, the picked ones, or everything the filter selects.
 */
export const files = {
  /** Screen explanation (`features/manage-onboarding`, `ExplanationPanel`). */
  explanation: {
    body: 'All files of the installation in one place: whatever people and agents attached to entries or uploaded here. A file belongs to one project and keeps its link when replaced. Deleting erases the bytes and leaves only a trace: name, type and who deleted it.',
  },
  intro:
    'Files of every project in one list. Find a file by name, sort the list, narrow it by type or project. Deleting erases the bytes for good; a trace stays in the entries that attached the file.',
  loading: 'Reading the files…',
  empty:
    'There are no files in this installation yet. Upload one here, or an agent attaches one to an entry.',
  emptyFiltered: 'No file matches the search and filters.',
  close: 'Close',
  cancel: 'Cancel',

  list: {
    label: 'Files',
    shown_one: '{{count, number}} file shown',
    shown_other: '{{count, number}} files shown',
    unopenedCount_one: '{{count, number}} image not opened in a long time',
    unopenedCount_other: '{{count, number}} images not opened in a long time',
    moreAvailable: 'more are available',
    more: 'Show more',
    loadingMore: 'Reading…',
  },

  units: { bytes: 'B', kilobytes: 'KB', megabytes: 'MB', gigabytes: 'GB' },

  filters: {
    label: 'Search and filters',
    search: 'Search by name',
    searchPlaceholder: 'Part of a file name',
    project: 'Project',
    allProjects: 'All projects',
    type: 'Type',
    sort: 'Sort by',
    descending: 'Descending',
    ascending: 'Ascending',
    direction: 'Direction: {{current}}',
    unopened: 'Not opened in a long time',
    unopenedTerm_one: 'Images not opened for {{count, number}} day. The term is',
    unopenedTerm_other: 'Images not opened for {{count, number}} days. The term is',
    unopenedSettings: 'an installation setting, changed in Settings',
    reset: 'Reset',
    types: {
      all: 'All types',
      image: 'Images',
      pdf: 'PDF',
      word: 'Word documents',
      excel: 'Excel tables',
      text: 'Text',
      audio: 'Audio',
      video: 'Video',
    },
    sorts: {
      added: 'Date added',
      opened: 'Last opened',
      size: 'Size',
      type: 'Type',
    },
  },

  item: {
    label: 'File {{name}}',
    select: 'Select {{name}}',
    project: 'Project {{key}}',
    addedBy: 'Added by {{author}}',
    addedByTracker: 'Added by the tracker',
    opened: 'Last opened',
    unopened: 'Not opened in a long time',
    neverOpened: 'Never opened',
    replaced: 'Replaced by {{author}}',
    replacedByTracker: 'Replaced by the tracker',
    refs_one: 'Attached in {{count, number}} entry, tasks: {{tasks, number}}',
    refs_other: 'Attached in {{count, number}} entries, tasks: {{tasks, number}}',
    noRefs: 'Not attached to any entry',
    archived: 'The project is archived: the file can be opened but not changed',
  },

  actions: {
    open: 'Open',
    download: 'Download',
    replace: 'Replace',
    delete: 'Delete',
  },

  preview: {
    title: '{{name}}',
    intro:
      'The file opens from the installation; this counts as its last opening. Only images are shown here — download any other kind.',
    loading: 'Reading the file…',
    notImage: 'This kind of file is not shown here. Download it instead.',
    alt: 'Image {{name}}',
  },

  upload: {
    open: 'Upload a file',
    title: 'Upload a file',
    intro: 'The file goes into one project and keeps that project until it is deleted.',
    project: 'Project',
    projectPlaceholder: 'Choose a project',
    noProjects: 'There is no project to put a file into. Create a project first.',
    file: 'File',
    name: 'Name',
    nameHint: 'Leave it empty to keep the name of the file on your computer.',
    submit: 'Upload',
    pending: 'Uploading…',
  },

  replace: {
    title: 'Replace {{name}}',
    intro:
      'The new bytes go under the same link: every entry that attached the file shows the new content. The old content is erased and there is no history of versions.',
    file: 'New file',
    name: 'New name',
    nameHint: 'Leave it empty to keep the current name.',
    submit: 'Replace',
    pending: 'Replacing…',
  },

  remove: {
    singleTitle: 'Delete {{name}}?',
    singleIntro:
      'The bytes are erased for good; a trace stays: name, type, size and who deleted it. Entries that attached the file will say it is deleted.',
    manyTitle_one: 'Delete {{count, number}} file?',
    manyTitle_other: 'Delete {{count, number}} files?',
    matchingTitle_one: 'Delete the {{count, number}} file the filter selected?',
    matchingTitle_other: 'Delete all {{count, number}} files the filter selected?',
    manyIntro:
      'The bytes of every file below are erased for good; a trace of each stays: name, type, size and who deleted it. Entries that attached a file will say it is deleted.',
    refs_one:
      'Attached in {{count, number}} entry (summed over the files; tasks: {{tasks, number}})',
    refs_other:
      'Attached in {{count, number}} entries (summed over the files; tasks: {{tasks, number}})',
    noRefs: 'None of them is attached to an entry.',
    counting: 'Counting the files the filter selects…',
    countFailed: 'Could not count the files. Try again.',
    countAgain: 'Count again',
    confirmCount: 'I am deleting exactly {{count, number}} of them',
    confirm: 'Delete',
    pending: 'Deleting…',
    done_one: 'Deleted {{count, number}} file.',
    done_other: 'Deleted {{count, number}} files.',
    mismatch:
      'The number of matching files changed to {{actual, number}} while this window was open: nothing was deleted. Check the new number and confirm again.',
    moreFiles_one: 'and {{count, number}} more file',
    moreFiles_other: 'and {{count, number}} more files',
  },

  selection: {
    selected_one: '{{count, number}} file selected',
    selected_other: '{{count, number}} files selected',
    selectAll: 'Select all shown',
    clear: 'Clear selection',
    deleteSelected: 'Delete selected',
    deleteMatching: 'Delete all selected by the filter',
    deleteUnopened: 'Delete all not opened in a long time',
    deleteEverything: 'Delete all files',
  },
};
