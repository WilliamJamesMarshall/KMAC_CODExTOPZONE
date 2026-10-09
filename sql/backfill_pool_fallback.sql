-- Reusable, source-linked fallback for pool entries without a named solution.
-- A NULL solution_name means the pool text has not been split into products.
begin;

insert into public.supplier_solutions
  (id, supplier_id, solution_name, description, source_pool_entry_id, status, verification_status)
select
  md5('pool-fallback-solution:' || p.id::text)::uuid,
  p.supplier_id,
  null,
  p.ai_solution_text,
  p.id,
  'candidate',
  'unreviewed'
from public.pool_entries p
where length(trim(coalesce(p.ai_solution_text, ''))) > 0
  and not exists (
    select 1 from public.supplier_solutions s
    where s.supplier_id = p.supplier_id
  )
on conflict (id) do nothing;

insert into public.capability_evidence
  (id, supplier_id, solution_id, pool_entry_id, evidence_text, evidence_type,
   evidence_strength, verification_status, mapping_method)
select
  md5('pool-solution-evidence:' || s.id::text)::uuid,
  s.supplier_id,
  s.id,
  s.source_pool_entry_id,
  s.description,
  'company_description',
  1,
  'candidate',
  'pool_listing'
from public.supplier_solutions s
where s.source_pool_entry_id is not null
on conflict (id) do nothing;

update public.suppliers s
set last_crawled_at = r.latest, updated_at = now()
from (
  select supplier_id, max(started_at) latest
  from public.crawl_runs
  group by supplier_id
) r
where r.supplier_id = s.id
  and s.last_crawled_at is distinct from r.latest;

commit;
