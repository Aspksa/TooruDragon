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


CREATE TABLE IF NOT EXISTS work_documents (
    id TEXT PRIMARY KEY,
    family_id TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    previous_document_id TEXT,
    title TEXT NOT NULL,
    original_name TEXT NOT NULL DEFAULT '',
    document_type TEXT NOT NULL,
    status TEXT NOT NULL,
    document_number TEXT NOT NULL DEFAULT '',
    document_date TEXT,
    year INTEGER,
    archive_path TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    source_path TEXT NOT NULL DEFAULT '',
    text_content TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    normalized_sha256 TEXT NOT NULL,
    structure_sha256 TEXT NOT NULL,
    passport_json TEXT NOT NULL DEFAULT '{}',
    dna_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(previous_document_id) REFERENCES work_documents(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_work_documents_content_hash
ON work_documents(content_sha256)
WHERE archived=0;

CREATE INDEX IF NOT EXISTS idx_work_documents_family_version
ON work_documents(family_id, version DESC);

CREATE INDEX IF NOT EXISTS idx_work_documents_type_date
ON work_documents(document_type, document_date);

CREATE INDEX IF NOT EXISTS idx_work_documents_status
ON work_documents(status, archived, updated_at DESC);

CREATE TABLE IF NOT EXISTS work_document_facts (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    fact_type TEXT NOT NULL,
    fact_key TEXT NOT NULL,
    value_text TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    provenance_json TEXT NOT NULL DEFAULT '{}',
    verified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES work_documents(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_work_document_facts_document
ON work_document_facts(document_id, fact_type, fact_key);

CREATE INDEX IF NOT EXISTS idx_work_document_facts_lookup
ON work_document_facts(fact_type, normalized_value);

CREATE TABLE IF NOT EXISTS work_document_issues (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    issue_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    resolved INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES work_documents(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_work_document_issues_document
ON work_document_issues(document_id, resolved, severity);

CREATE TABLE IF NOT EXISTS work_document_relations (
    id TEXT PRIMARY KEY,
    source_document_id TEXT NOT NULL,
    target_document_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    score REAL NOT NULL DEFAULT 1.0,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(source_document_id) REFERENCES work_documents(id) ON DELETE CASCADE,
    FOREIGN KEY(target_document_id) REFERENCES work_documents(id) ON DELETE CASCADE,
    UNIQUE(source_document_id, target_document_id, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_work_document_relations_source
ON work_document_relations(source_document_id, relation_type);

CREATE INDEX IF NOT EXISTS idx_work_document_relations_target
ON work_document_relations(target_document_id, relation_type);


CREATE TABLE IF NOT EXISTS work_document_ingest_log (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'manual',
    status TEXT NOT NULL,
    document_id TEXT,
    error_type TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES work_documents(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_work_document_ingest_log_created
ON work_document_ingest_log(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_work_document_ingest_log_status
ON work_document_ingest_log(status, created_at DESC);


CREATE TABLE IF NOT EXISTS work_employee_fuel_cards (
    id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL,
    card_number TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(employee_id) REFERENCES work_employees(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_employee_fuel_cards_active_number
ON work_employee_fuel_cards(card_number)
WHERE active=1;

CREATE INDEX IF NOT EXISTS idx_employee_fuel_cards_employee
ON work_employee_fuel_cards(employee_id, active, valid_from, valid_to);

CREATE TABLE IF NOT EXISTS garage_vehicles (
    id TEXT PRIMARY KEY,
    registration_number TEXT NOT NULL UNIQUE,
    vin TEXT NOT NULL DEFAULT '',
    make TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    department TEXT NOT NULL DEFAULT '',
    fuel_type TEXT NOT NULL DEFAULT '',
    tank_capacity_l REAL,
    default_norm_l_per_100km REAL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_garage_vehicles_vin
ON garage_vehicles(vin)
WHERE vin!='';

CREATE TABLE IF NOT EXISTS garage_driver_vehicle_assignments (
    id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL,
    vehicle_id TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'manual',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(employee_id) REFERENCES work_employees(id) ON DELETE CASCADE,
    FOREIGN KEY(vehicle_id) REFERENCES garage_vehicles(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_garage_driver_vehicle_employee
ON garage_driver_vehicle_assignments(employee_id, active, valid_from, valid_to);

CREATE INDEX IF NOT EXISTS idx_garage_driver_vehicle_vehicle
ON garage_driver_vehicle_assignments(vehicle_id, active, valid_from, valid_to);

CREATE TABLE IF NOT EXISTS garage_waybills (
    id TEXT PRIMARY KEY,
    waybill_number TEXT NOT NULL DEFAULT '',
    trip_date TEXT,
    employee_id TEXT,
    vehicle_id TEXT,
    odometer_start REAL,
    odometer_end REAL,
    distance_km REAL NOT NULL DEFAULT 0,
    fuel_open_l REAL NOT NULL DEFAULT 0,
    fuel_issued_l REAL NOT NULL DEFAULT 0,
    fuel_close_l REAL NOT NULL DEFAULT 0,
    norm_l_per_100km REAL,
    actual_consumption_l REAL NOT NULL DEFAULT 0,
    norm_consumption_l REAL,
    deviation_l REAL,
    source_document_id TEXT,
    batch_id TEXT,
    organization TEXT NOT NULL DEFAULT '',
    department TEXT NOT NULL DEFAULT '',
    vehicle_make TEXT NOT NULL DEFAULT '',
    vehicle_model TEXT NOT NULL DEFAULT '',
    vehicle_vin TEXT NOT NULL DEFAULT '',
    garage_number TEXT NOT NULL DEFAULT '',
    driver_name TEXT NOT NULL DEFAULT '',
    personnel_number TEXT NOT NULL DEFAULT '',
    departure_time TEXT,
    return_time TEXT,
    refueled_l REAL NOT NULL DEFAULT 0,
    fuel_name TEXT NOT NULL DEFAULT '',
    route TEXT NOT NULL DEFAULT '',
    assignment_text TEXT NOT NULL DEFAULT '',
    fuel_card_number TEXT NOT NULL DEFAULT '',
    source_pages_json TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 0,
    needs_review INTEGER NOT NULL DEFAULT 0,
    processing_status TEXT NOT NULL DEFAULT 'manual',
    folder_path TEXT NOT NULL DEFAULT '',
    individual_pdf_path TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(employee_id) REFERENCES work_employees(id) ON DELETE SET NULL,
    FOREIGN KEY(vehicle_id) REFERENCES garage_vehicles(id) ON DELETE SET NULL,
    FOREIGN KEY(source_document_id) REFERENCES work_documents(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_garage_waybills_month
ON garage_waybills(trip_date, vehicle_id, employee_id);

CREATE TABLE IF NOT EXISTS garage_fuel_statements (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL UNIQUE,
    original_name TEXT NOT NULL DEFAULT '',
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    card_count INTEGER NOT NULL DEFAULT 0,
    transaction_count INTEGER NOT NULL DEFAULT 0,
    total_liters REAL NOT NULL DEFAULT 0,
    total_amount REAL NOT NULL DEFAULT 0,
    parser TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES work_documents(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_garage_fuel_statements_period
ON garage_fuel_statements(period_start, period_end);

CREATE TABLE IF NOT EXISTS garage_fuel_transactions (
    id TEXT PRIMARY KEY,
    statement_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    source_row INTEGER NOT NULL,
    card_number TEXT NOT NULL,
    holder_label TEXT NOT NULL DEFAULT '',
    employee_id TEXT,
    vehicle_id TEXT,
    operation TEXT NOT NULL DEFAULT '',
    operation_date TEXT NOT NULL,
    operation_time TEXT NOT NULL DEFAULT '',
    station TEXT NOT NULL DEFAULT '',
    fuel_name TEXT NOT NULL DEFAULT '',
    fuel_kind TEXT NOT NULL DEFAULT '',
    price_per_liter REAL NOT NULL DEFAULT 0,
    quantity_l REAL NOT NULL DEFAULT 0,
    amount REAL NOT NULL DEFAULT 0,
    resolution_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(statement_id) REFERENCES garage_fuel_statements(id) ON DELETE CASCADE,
    FOREIGN KEY(document_id) REFERENCES work_documents(id) ON DELETE CASCADE,
    FOREIGN KEY(employee_id) REFERENCES work_employees(id) ON DELETE SET NULL,
    FOREIGN KEY(vehicle_id) REFERENCES garage_vehicles(id) ON DELETE SET NULL,
    UNIQUE(statement_id, source_row)
);

CREATE INDEX IF NOT EXISTS idx_garage_fuel_transactions_card_date
ON garage_fuel_transactions(card_number, operation_date);

CREATE INDEX IF NOT EXISTS idx_garage_fuel_transactions_vehicle_date
ON garage_fuel_transactions(vehicle_id, operation_date);

CREATE INDEX IF NOT EXISTS idx_garage_fuel_transactions_resolution
ON garage_fuel_transactions(resolution_status, operation_date);


CREATE TABLE IF NOT EXISTS work_employee_schedules (
    id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    weekdays_json TEXT NOT NULL DEFAULT '[0,1,2,3,4]',
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(employee_id) REFERENCES work_employees(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_work_employee_schedules_lookup
ON work_employee_schedules(employee_id, active, valid_from, valid_to);

CREATE TABLE IF NOT EXISTS work_waybill_batches (
    id TEXT PRIMARY KEY,
    document_id TEXT,
    original_name TEXT NOT NULL,
    source_path TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    size_bytes INTEGER NOT NULL,
    page_count INTEGER NOT NULL DEFAULT 0,
    uploaded_by TEXT NOT NULL DEFAULT 'user',
    source TEXT NOT NULL DEFAULT 'documents',
    status TEXT NOT NULL DEFAULT 'uploaded',
    stage TEXT NOT NULL DEFAULT 'uploaded',
    pages_processed INTEGER NOT NULL DEFAULT 0,
    pages_ocr INTEGER NOT NULL DEFAULT 0,
    waybills_detected INTEGER NOT NULL DEFAULT 0,
    waybills_completed INTEGER NOT NULL DEFAULT 0,
    errors_count INTEGER NOT NULL DEFAULT 0,
    review_count INTEGER NOT NULL DEFAULT 0,
    progress_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES work_documents(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_work_waybill_batches_status
ON work_waybill_batches(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS work_waybill_batch_pages (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    waybill_id TEXT,
    ocr_engine TEXT NOT NULL DEFAULT '',
    ocr_text TEXT NOT NULL DEFAULT '',
    ocr_blocks_json TEXT NOT NULL DEFAULT '[]',
    ocr_tables_json TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 0,
    image_path TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(batch_id) REFERENCES work_waybill_batches(id) ON DELETE CASCADE,
    FOREIGN KEY(waybill_id) REFERENCES garage_waybills(id) ON DELETE SET NULL,
    UNIQUE(batch_id, page_number)
);

CREATE INDEX IF NOT EXISTS idx_work_waybill_batch_pages_batch
ON work_waybill_batch_pages(batch_id, page_number);

CREATE TABLE IF NOT EXISTS garage_waybill_fields (
    waybill_id TEXT NOT NULL,
    field_key TEXT NOT NULL,
    original_value TEXT NOT NULL DEFAULT '',
    corrected_value TEXT,
    confidence REAL NOT NULL DEFAULT 0,
    verified INTEGER NOT NULL DEFAULT 0,
    provenance_json TEXT NOT NULL DEFAULT '{}',
    corrected_at TEXT,
    corrected_by TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(waybill_id, field_key),
    FOREIGN KEY(waybill_id) REFERENCES garage_waybills(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_garage_waybill_fields_review
ON garage_waybill_fields(verified, confidence, field_key);

CREATE TABLE IF NOT EXISTS garage_waybill_anomalies (
    id TEXT PRIMARY KEY,
    waybill_id TEXT NOT NULL,
    anomaly_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    resolved INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(waybill_id) REFERENCES garage_waybills(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_garage_waybill_anomalies_waybill
ON garage_waybill_anomalies(waybill_id, resolved, severity);

CREATE TABLE IF NOT EXISTS work_overtime_candidates (
    id TEXT PRIMARY KEY,
    employee_id TEXT,
    work_date TEXT,
    waybill_id TEXT NOT NULL UNIQUE,
    scheduled_start TEXT,
    scheduled_end TEXT,
    actual_departure TEXT,
    actual_return TEXT,
    overtime_before_minutes INTEGER NOT NULL DEFAULT 0,
    overtime_after_minutes INTEGER NOT NULL DEFAULT 0,
    overtime_total_minutes INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'detected',
    confidence REAL NOT NULL DEFAULT 0,
    comment TEXT NOT NULL DEFAULT '',
    applied_entry_id TEXT,
    applied_minutes INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(employee_id) REFERENCES work_employees(id) ON DELETE SET NULL,
    FOREIGN KEY(waybill_id) REFERENCES garage_waybills(id) ON DELETE CASCADE,
    FOREIGN KEY(applied_entry_id) REFERENCES work_timesheet_entries(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_work_overtime_candidates_review
ON work_overtime_candidates(status, work_date, employee_id);

CREATE TABLE IF NOT EXISTS work_entity_relations (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    source_document_id TEXT,
    confidence REAL NOT NULL DEFAULT 1.0,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(source_document_id) REFERENCES work_documents(id) ON DELETE SET NULL,
    UNIQUE(source_type, source_id, relation_type, target_type, target_id)
);

CREATE INDEX IF NOT EXISTS idx_work_entity_relations_source
ON work_entity_relations(source_type, source_id, relation_type);

CREATE INDEX IF NOT EXISTS idx_work_entity_relations_target
ON work_entity_relations(target_type, target_id, relation_type);

CREATE TABLE IF NOT EXISTS work_audit_log (
    id TEXT PRIMARY KEY,
    actor TEXT NOT NULL DEFAULT 'system',
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    field_name TEXT NOT NULL DEFAULT '',
    original_value TEXT,
    new_value TEXT,
    reason TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    source_document_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(source_document_id) REFERENCES work_documents(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_work_audit_entity
ON work_audit_log(entity_type, entity_id, created_at DESC);
