PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS system_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS core_state (
    core_name TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workshop_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    path TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS home_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS work_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    payload_json TEXT,
    created_at TEXT NOT NULL
);


CREATE TABLE IF NOT EXISTS core_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    core_name TEXT NOT NULL,
    action TEXT NOT NULL,
    ok INTEGER NOT NULL,
    message TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_core_actions_created_at
ON core_actions(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_core_actions_core_name
ON core_actions(core_name);


CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    parent_id TEXT,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    state TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    available_at TEXT NOT NULL,
    lease_owner TEXT,
    lease_until TEXT,
    idempotency_key TEXT,
    trace_id TEXT NOT NULL,
    required_capability TEXT,
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_idempotency_key
ON tasks(idempotency_key)
WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_tasks_claim
ON tasks(state, available_at, priority, created_at);

CREATE INDEX IF NOT EXISTS idx_tasks_workflow
ON tasks(workflow_id, created_at);

CREATE TABLE IF NOT EXISTS task_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    message TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(task_id) REFERENCES tasks(id)
);

CREATE INDEX IF NOT EXISTS idx_task_transitions_task
ON task_transitions(task_id, id);


CREATE TABLE IF NOT EXISTS durable_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    topic TEXT NOT NULL,
    source TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_durable_events_topic_sequence
ON durable_events(topic, sequence);

CREATE TABLE IF NOT EXISTS event_offsets (
    consumer TEXT PRIMARY KEY,
    sequence INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_dead_letters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    consumer TEXT NOT NULL,
    error TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_event_dead_letters_consumer
ON event_dead_letters(consumer, id);


CREATE TABLE IF NOT EXISTS deployment_state (
    core_name TEXT PRIMARY KEY,
    candidate_json TEXT NOT NULL,
    previous_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);


CREATE TABLE IF NOT EXISTS ai_conversations (
    id TEXT PRIMARY KEY,
    title TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ai_conversations_updated
ON ai_conversations(updated_at DESC);

CREATE TABLE IF NOT EXISTS ai_messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    trace_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(conversation_id) REFERENCES ai_conversations(id)
);

CREATE INDEX IF NOT EXISTS idx_ai_messages_conversation
ON ai_messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS ai_memory_items (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ai_memory_scope_created
ON ai_memory_items(scope, created_at DESC);


CREATE TABLE IF NOT EXISTS ai_documents (
    id TEXT PRIMARY KEY,
    title TEXT,
    source TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_document_chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES ai_documents(id) ON DELETE CASCADE,
    UNIQUE(document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_ai_document_chunks_document
ON ai_document_chunks(document_id, chunk_index);


CREATE TABLE IF NOT EXISTS reasoning_runs (
    id TEXT PRIMARY KEY,
    trace_id TEXT,
    mode TEXT NOT NULL,
    score INTEGER NOT NULL,
    threshold INTEGER NOT NULL,
    branch_count INTEGER NOT NULL DEFAULT 0,
    depth INTEGER NOT NULL DEFAULT 1,
    contradiction_detected INTEGER NOT NULL DEFAULT 0,
    fallback INTEGER NOT NULL DEFAULT 0,
    branch_names_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    feedback_score REAL,
    feedback_source TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reasoning_runs_created
ON reasoning_runs(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_reasoning_runs_trace
ON reasoning_runs(trace_id);

CREATE TABLE IF NOT EXISTS reasoning_run_branches (
    run_id TEXT NOT NULL,
    branch_name TEXT NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY(run_id, branch_name),
    FOREIGN KEY(run_id) REFERENCES reasoning_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reasoning_branch_stats (
    branch_name TEXT PRIMARY KEY,
    attempts INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    feedback_count INTEGER NOT NULL DEFAULT 0,
    feedback_sum REAL NOT NULL DEFAULT 0.0,
    weight REAL NOT NULL DEFAULT 1.0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reasoning_mode_stats (
    mode TEXT PRIMARY KEY,
    runs INTEGER NOT NULL DEFAULT 0,
    feedback_count INTEGER NOT NULL DEFAULT 0,
    feedback_sum REAL NOT NULL DEFAULT 0.0,
    updated_at TEXT NOT NULL
);


CREATE TABLE IF NOT EXISTS work_employees (
    id TEXT PRIMARY KEY,
    personnel_number TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    department TEXT NOT NULL DEFAULT '',
    position TEXT NOT NULL DEFAULT '',
    schedule_type TEXT NOT NULL DEFAULT '5/2',
    weekly_hours REAL NOT NULL DEFAULT 40,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_work_employees_department_name
ON work_employees(department, full_name);

CREATE TABLE IF NOT EXISTS work_timesheet_entries (
    id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL,
    work_date TEXT NOT NULL,
    status TEXT NOT NULL,
    planned_hours REAL NOT NULL DEFAULT 0,
    actual_hours REAL NOT NULL DEFAULT 0,
    overtime_hours REAL NOT NULL DEFAULT 0,
    night_hours REAL NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(employee_id) REFERENCES work_employees(id) ON DELETE CASCADE,
    UNIQUE(employee_id, work_date)
);

CREATE INDEX IF NOT EXISTS idx_work_timesheet_month
ON work_timesheet_entries(work_date, employee_id);

CREATE INDEX IF NOT EXISTS idx_work_timesheet_employee
ON work_timesheet_entries(employee_id, work_date);


CREATE TABLE IF NOT EXISTS work_timesheet_custom_columns (
    id TEXT PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    value_type TEXT NOT NULL DEFAULT 'text',
    sort_order INTEGER NOT NULL DEFAULT 100,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_work_timesheet_custom_columns_order
ON work_timesheet_custom_columns(active, sort_order, label);

CREATE TABLE IF NOT EXISTS work_timesheet_custom_values (
    entry_id TEXT NOT NULL,
    column_id TEXT NOT NULL,
    value_text TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY(entry_id, column_id),
    FOREIGN KEY(entry_id) REFERENCES work_timesheet_entries(id) ON DELETE CASCADE,
    FOREIGN KEY(column_id) REFERENCES work_timesheet_custom_columns(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_work_timesheet_custom_values_column
ON work_timesheet_custom_values(column_id, entry_id);
