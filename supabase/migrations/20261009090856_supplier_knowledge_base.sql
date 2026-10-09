-- Supplier knowledge base. Raw source records and inferred capabilities stay separate.
create table public.ax_tasks (
  task_id text primary key,
  task_name text not null,
  parent_group text,
  business_purpose text,
  expected_output text,
  activity_tags jsonb,
  boundary_rule text,
  activity_layer text,
  taxonomy_version text not null,
  is_active boolean not null default true,
  review_status text not null default 'unreviewed',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.suppliers (
  id uuid primary key default gen_random_uuid(),
  canonical_name text not null,
  legal_name text,
  business_number text,
  homepage_url text,
  homepage_host text,
  company_summary text,
  founded_year integer,
  region text,
  status text not null default 'pending'
    check (status in ('pending', 'active', 'inactive', 'website_unreachable', 'duplicate', 'excluded')),
  verification_status text not null default 'unreviewed'
    check (verification_status in ('unreviewed', 'ai_extracted', 'human_reviewed', 'verified')),
  last_crawled_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- A pool row is a dated source record, not the identity of a legal company.
create table public.pool_entries (
  id uuid primary key default gen_random_uuid(),
  supplier_id uuid not null references public.suppliers(id),
  source_program text not null,
  source_year integer not null,
  sply_pool_no bigint not null,
  source_url text not null,
  source_hash text not null,
  raw_record jsonb not null,
  specialization text,
  ai_solution_text text,
  homepage_raw text,
  fetched_at timestamptz not null,
  created_at timestamptz not null default now(),
  unique (source_program, source_year, sply_pool_no)
);

create table public.supplier_aliases (
  id uuid primary key default gen_random_uuid(),
  supplier_id uuid not null references public.suppliers(id),
  alias text not null,
  alias_type text not null default 'other',
  unique (supplier_id, alias)
);

create table public.supplier_domains (
  id uuid primary key default gen_random_uuid(),
  supplier_id uuid not null references public.suppliers(id),
  domain text not null,
  base_url text not null,
  domain_type text not null default 'corporate',
  is_primary boolean not null default false,
  is_active boolean not null default true,
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  unique (supplier_id, base_url)
);
create unique index supplier_domains_one_primary on public.supplier_domains(supplier_id)
  where is_primary;

create table public.crawl_runs (
  id uuid primary key default gen_random_uuid(),
  supplier_id uuid not null references public.suppliers(id),
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null default 'pending',
  crawler_version text not null,
  pages_discovered integer not null default 0,
  pages_fetched integer not null default 0,
  pages_failed integer not null default 0,
  robots_allowed boolean,
  error_message text
);

create table public.web_pages (
  id uuid primary key default gen_random_uuid(),
  supplier_id uuid not null references public.suppliers(id),
  crawl_run_id uuid not null references public.crawl_runs(id),
  url text not null,
  canonical_url text,
  page_type text not null default 'unknown',
  title text,
  clean_text text,
  storage_path text,
  content_hash text not null,
  http_status integer,
  language text,
  published_at timestamptz,
  crawled_at timestamptz not null default now(),
  is_active boolean not null default true,
  unique (crawl_run_id, url)
);

create table public.page_chunks (
  id uuid primary key default gen_random_uuid(),
  page_id uuid not null references public.web_pages(id),
  supplier_id uuid not null references public.suppliers(id),
  chunk_index integer not null,
  chunk_text text not null,
  token_count integer,
  content_hash text not null,
  created_at timestamptz not null default now(),
  unique (page_id, chunk_index)
);
-- Add an embedding column and vector index only after the model/dimensions are chosen.

create table public.supplier_solutions (
  id uuid primary key default gen_random_uuid(),
  supplier_id uuid not null references public.suppliers(id),
  solution_name text,
  description text not null,
  solution_category text,
  deployment_type text,
  target_industries jsonb,
  source_pool_entry_id uuid references public.pool_entries(id),
  source_page_id uuid references public.web_pages(id),
  status text not null default 'candidate',
  verification_status text not null default 'unreviewed',
  first_seen_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  check (source_pool_entry_id is not null or source_page_id is not null)
);

create table public.supplier_projects (
  id uuid primary key default gen_random_uuid(),
  supplier_id uuid not null references public.suppliers(id),
  project_name text not null,
  client_name text,
  client_industry text,
  problem text,
  solution_summary text,
  technologies jsonb,
  project_date date,
  outcome text,
  source_pool_entry_id uuid references public.pool_entries(id),
  source_page_id uuid references public.web_pages(id),
  source_url text,
  verification_status text not null default 'unreviewed',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (source_pool_entry_id is not null or source_page_id is not null)
);

create table public.solution_task_links (
  id uuid primary key default gen_random_uuid(),
  solution_id uuid not null references public.supplier_solutions(id),
  task_id text not null references public.ax_tasks(task_id),
  confidence numeric(4, 3) check (confidence between 0 and 1),
  mapping_method text not null,
  verification_status text not null default 'candidate',
  model_version text,
  prompt_version text,
  created_at timestamptz not null default now(),
  unique (solution_id, task_id)
);

create table public.project_task_links (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.supplier_projects(id),
  task_id text not null references public.ax_tasks(task_id),
  confidence numeric(4, 3) check (confidence between 0 and 1),
  mapping_method text not null,
  verification_status text not null default 'candidate',
  created_at timestamptz not null default now(),
  unique (project_id, task_id)
);

create table public.capability_evidence (
  id uuid primary key default gen_random_uuid(),
  supplier_id uuid not null references public.suppliers(id),
  solution_id uuid references public.supplier_solutions(id),
  project_id uuid references public.supplier_projects(id),
  task_id text references public.ax_tasks(task_id),
  pool_entry_id uuid references public.pool_entries(id),
  page_id uuid references public.web_pages(id),
  chunk_id uuid references public.page_chunks(id),
  evidence_text text not null,
  evidence_type text not null,
  evidence_strength smallint not null check (evidence_strength between 0 and 4),
  confidence numeric(4, 3) check (confidence between 0 and 1),
  verification_status text not null default 'candidate',
  mapping_method text not null,
  extractor_model text,
  extractor_version text,
  prompt_version text,
  created_at timestamptz not null default now(),
  check (pool_entry_id is not null or page_id is not null or chunk_id is not null)
);

create table public.supplier_task_profiles (
  supplier_id uuid not null references public.suppliers(id),
  task_id text not null references public.ax_tasks(task_id),
  capability_score numeric(5, 4) not null check (capability_score between 0 and 1),
  solution_count integer not null default 0,
  project_count integer not null default 0,
  verified_project_count integer not null default 0,
  max_evidence_strength smallint not null default 0,
  avg_confidence numeric(4, 3),
  industry_tags jsonb,
  deployment_types jsonb,
  latest_evidence_at timestamptz,
  last_calculated_at timestamptz not null default now(),
  scoring_version text not null,
  primary key (supplier_id, task_id)
);

create table public.processing_jobs (
  id uuid primary key default gen_random_uuid(),
  supplier_id uuid references public.suppliers(id),
  entity_type text not null,
  entity_id uuid,
  job_type text not null,
  status text not null default 'pending',
  attempt_count integer not null default 0,
  scheduled_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  error_message text
);

create table public.ncs_units (
  id uuid primary key default gen_random_uuid(),
  ncs_code text unique,
  large_category text,
  middle_category text,
  small_category text,
  sub_category text,
  competency_unit text
);

create table public.ncs_task_map (
  id uuid primary key default gen_random_uuid(),
  ncs_unit_id uuid not null references public.ncs_units(id),
  task_id text not null references public.ax_tasks(task_id),
  confidence numeric(4, 3) check (confidence between 0 and 1),
  mapping_reason text,
  mapping_version text not null,
  unique (ncs_unit_id, task_id, mapping_version)
);

create index pool_entries_supplier_idx on public.pool_entries(supplier_id);
create index suppliers_homepage_host_idx on public.suppliers(homepage_host);
create index suppliers_status_idx on public.suppliers(status);
create index crawl_runs_supplier_idx on public.crawl_runs(supplier_id, started_at desc);
create index web_pages_supplier_type_idx on public.web_pages(supplier_id, page_type);
create index web_pages_content_hash_idx on public.web_pages(content_hash);
create index page_chunks_supplier_idx on public.page_chunks(supplier_id);
create index solution_task_links_task_idx on public.solution_task_links(task_id);
create index project_task_links_task_idx on public.project_task_links(task_id);
create index capability_evidence_supplier_task_idx on public.capability_evidence(supplier_id, task_id);
create index supplier_task_profiles_task_score_idx on public.supplier_task_profiles(task_id, capability_score desc);
create index processing_jobs_status_idx on public.processing_jobs(status, scheduled_at);

-- Only the server-side worker writes. No raw source or evidence table is exposed
-- to browser roles. Catalog reads can be granted once a review workflow exists.
do $$
declare table_name text;
begin
  foreach table_name in array array[
    'ax_tasks', 'suppliers', 'pool_entries', 'supplier_aliases', 'supplier_domains',
    'crawl_runs', 'web_pages', 'page_chunks', 'supplier_solutions',
    'supplier_projects', 'solution_task_links', 'project_task_links',
    'capability_evidence', 'supplier_task_profiles', 'processing_jobs',
    'ncs_units', 'ncs_task_map'
  ] loop
    execute format('alter table public.%I enable row level security', table_name);
    execute format('revoke all on public.%I from anon, authenticated', table_name);
  end loop;
end $$;

insert into storage.buckets (id, name, public)
values ('supplier-crawl', 'supplier-crawl', false)
on conflict (id) do nothing;
