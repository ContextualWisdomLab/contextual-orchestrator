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
  prompt_text text not null,
  run_mode text not null,
  answer_text text not null,
  created_at timestamptz not null default now()
);

create table workflow_step (
  workflow_step_id text primary key,
  workflow_run_id text not null references workflow_run(workflow_run_id),
  agent_id text not null references agent_pool(agent_id),
  role_name text not null,
  subtask_text text not null,
  access_list text not null,
  output_text text not null,
  started_at timestamptz,
  finished_at timestamptz
);

create table audit_event (
  audit_event_id text primary key,
  workflow_run_id text references workflow_run(workflow_run_id),
  event_type text not null,
  event_detail text not null,
  created_at timestamptz not null default now()
);

