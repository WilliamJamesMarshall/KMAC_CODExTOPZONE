-- Record unmatched suppliers for explicit AX Task review. No worker is attached.
insert into public.processing_jobs
  (id, supplier_id, entity_type, entity_id, job_type, status)
select
  md5('ax-task-review:' || s.id::text)::uuid,
  s.id,
  'supplier',
  s.id,
  'ax_task_review',
  'pending'
from public.suppliers s
where not exists (
  select 1 from public.capability_evidence e
  where e.supplier_id = s.id and e.task_id is not null
)
on conflict (id) do nothing;
