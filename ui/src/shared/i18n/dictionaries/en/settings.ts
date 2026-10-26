/**
 * The «Settings» screen (TRK-749, the owner's word TRK~31#4): seven installation
 * parameters. The value lives in the database and an administrator edits it; the
 * environment is the default.
 *
 * Each hint says what the parameter changes and when a new value takes effect
 * (TRK-742#7).
 */
export const settings = {
  intro:
    'How this installation works. The value is stored in the installation itself; until an administrator enters one, the value from the environment (the .env file) is in force, and without that, the tracker default.',
  loadingMe: 'Asking the installation who you are…',
  loading: 'Reading the installation settings…',
  readOnly:
    'An administrator of the installation edits the settings; you see what is in force. Your account has no administrator flag.',

  sources: {
    database: 'database',
    environment: 'environment',
    default: 'default',
  },

  boolean: {
    on: 'On',
    off: 'Off',
  },

  units: {
    seconds: 's',
    minutes: 'min',
    hours: 'h',
    days: 'd',
    bytes: 'B',
    kilobytes: 'KB',
    megabytes: 'MB',
    chars: 'characters',
    count: 'items',
  },

  row: {
    value: 'In force',
    default: 'Without an edit',
    defaultFromEnv: 'from the environment ({{name}})',
    defaultFromCode: 'tracker default',
    changed: 'Changed',
    neverChanged: 'never',
    changedBy: 'by {{author}},',
    changedByTracker: 'by the tracker itself,',
  },

  form: {
    label: 'Edit: {{name}}',
    newValue: 'New value',
    unit: 'Unit',
    save: 'Save',
    reset: 'Take from the environment',
  },

  errors: {
    not_an_integer: 'A whole number is needed, with no signs or spaces.',
    not_a_boolean: 'Choose «On» or «Off».',
    not_a_duration: 'The period does not parse: enter a whole number and choose a unit.',
    out_of_range: 'Out of range: from {{min}} to {{max}} is allowed. The previous value stays.',
  },

  items: {
    session_hours: {
      title: 'Session length',
      hint: 'How long a sign-in to the interface lasts. A new value applies to new sessions; the ones already issued do not change. Variable TRACKER_SESSION_HOURS.',
    },
    oauth_access_ttl: {
      title: 'Agent connection length',
      hint: 'How long an agent connection by OAuth lasts. A new value applies to new connections; the ones already issued do not change. Variable TRACKER_OAUTH_ACCESS_TTL.',
    },
    mcp_page_size: {
      title: 'MCP page size',
      hint: 'How many records an agent gets from one MCP tool call. Applies from the next call. Variable TRACKER_MCP_PAGE_SIZE.',
    },
    mcp_text_limit: {
      title: 'MCP text cut-off',
      hint: 'How many characters of a long text MCP returns in a search result; the rest is cut. Applies from the next call. Variable TRACKER_MCP_TEXT_LIMIT.',
    },
    release_check: {
      title: 'Check for new releases',
      hint: 'Whether to ask GitHub for a new Casefile release — the only way this installation reaches out. Applies from the next check. Variable TRACKER_RELEASE_CHECK.',
    },
    file_max_bytes: {
      title: 'Largest file size',
      hint: 'The largest file the installation accepts. Applies from the next upload. Variable TRACKER_FILE_MAX_BYTES.',
    },
    file_unopened_days: {
      title: 'Images unopened for',
      hint: 'After how many days without a single opening an image counts as unopened. It is a mark: the installation deletes nothing by itself. Variable TRACKER_FILE_UNOPENED_DAYS.',
    },
  },
} as const;
