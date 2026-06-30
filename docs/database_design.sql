create table agent_pool (
  agent_id text primary key,
  model_name text not null,
  provider_name text not null,
  base_url text not null,
  tag_list text not null,
  priority_rank integer not null default 0,
  enabled_flag boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table orchestration_policy (
  policy_id text primary key,
  policy_name text not null,
  route_threshold numeric(6, 3) not null,
  conduct_threshold numeric(6, 3) not null,
  verifier_required boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table workflow_run (
  workflow_run_id text primary key,
  policy_id text not null references orchestration_policy(policy_id),
  prompt_ciphertext bytea not null,
  prompt_preview_text text not null,
  run_mode text not null,
  answer_ciphertext bytea not null,
  answer_preview_text text not null,
  redaction_version text not null,
  retention_expires_at timestamptz not null,
  deleted_at timestamptz,
  created_at timestamptz not null default now(),
  constraint workflow_run_preview_limit check (
    char_length(prompt_preview_text) <= 256
    and char_length(answer_preview_text) <= 256
  )
);

create table workflow_step (
  workflow_step_id text primary key,
  workflow_run_id text not null references workflow_run(workflow_run_id),
  agent_id text not null references agent_pool(agent_id),
  role_name text not null,
  subtask_ciphertext bytea not null,
  subtask_preview_text text not null,
  access_list text not null,
  output_ciphertext bytea not null,
  output_preview_text text not null,
  redaction_version text not null,
  retention_expires_at timestamptz not null,
  deleted_at timestamptz,
  started_at timestamptz,
  finished_at timestamptz,
  constraint workflow_step_preview_limit check (
    char_length(subtask_preview_text) <= 256
    and char_length(output_preview_text) <= 256
  )
);

create table audit_event (
  audit_event_id text primary key,
  workflow_run_id text references workflow_run(workflow_run_id),
  event_type text not null,
  event_detail_json jsonb not null,
  retention_expires_at timestamptz not null,
  deleted_at timestamptz,
  created_at timestamptz not null default now()
);

create index workflow_run_retention_idx
  on workflow_run (retention_expires_at)
  where deleted_at is null;

create index workflow_step_retention_idx
  on workflow_step (retention_expires_at)
  where deleted_at is null;

create index audit_event_retention_idx
  on audit_event (retention_expires_at)
  where deleted_at is null;

create view workflow_run_safe_view as
select
  workflow_run_id,
  policy_id,
  prompt_preview_text,
  run_mode,
  answer_preview_text,
  redaction_version,
  retention_expires_at,
  created_at
from workflow_run
where deleted_at is null;

create function purge_expired_orchestration_data(p_now timestamptz default now())
returns integer
language plpgsql
as $$
declare
  purged_count integer;
begin
  update workflow_step
  set
    subtask_ciphertext = '\x'::bytea,
    output_ciphertext = '\x'::bytea,
    subtask_preview_text = '[deleted]',
    output_preview_text = '[deleted]',
    deleted_at = p_now
  where deleted_at is null and retention_expires_at <= p_now;

  update workflow_run
  set
    prompt_ciphertext = '\x'::bytea,
    answer_ciphertext = '\x'::bytea,
    prompt_preview_text = '[deleted]',
    answer_preview_text = '[deleted]',
    deleted_at = p_now
  where deleted_at is null and retention_expires_at <= p_now;

  update audit_event
  set
    event_detail_json = '{"deleted": true}'::jsonb,
    deleted_at = p_now
  where deleted_at is null and retention_expires_at <= p_now;

  get diagnostics purged_count = row_count;
  return purged_count;
end;
$$;
