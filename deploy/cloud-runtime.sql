-- Run once in the existing Supabase project's SQL Editor before Cloud Run startup.
-- Re-running preserves counters. No supplier tables or browser policies are changed.
begin;

create table if not exists public.oss_runtime_state (
  id integer primary key check (id = 1),
  quota_month date not null,
  accepted_count integer not null default 0 check (accepted_count >= 0),
  next_allowed_at timestamptz not null default '-infinity',
  lease_token uuid,
  lease_until timestamptz not null default '-infinity',
  success_count bigint not null default 0,
  failure_count bigint not null default 0,
  success_seconds double precision not null default 0,
  failure_seconds double precision not null default 0
);
alter table public.oss_runtime_state enable row level security;
revoke all on public.oss_runtime_state from public, anon, authenticated;
grant select, update on public.oss_runtime_state to service_role;
insert into public.oss_runtime_state (id, quota_month)
values (1, date_trunc('month', now() at time zone 'Asia/Seoul')::date)
on conflict (id) do nothing;

create or replace function public.oss_claim_analysis(
  p_token uuid, p_monthly_limit integer, p_interval_seconds integer, p_lease_seconds integer
) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare
  v_state public.oss_runtime_state%rowtype;
  v_now timestamptz := clock_timestamp();
  v_month date := date_trunc('month', v_now at time zone 'Asia/Seoul')::date;
  v_count integer;
begin
  if p_token is null or p_monthly_limit is null or p_monthly_limit not between 1 and 10000
     or p_interval_seconds is null or p_interval_seconds not between 1 and 3600
     or p_lease_seconds is null or p_lease_seconds not between 70 and 900 then
    raise exception 'Invalid analysis limits';
  end if;
  select * into strict v_state from public.oss_runtime_state where id = 1 for update;
  v_count := case when v_state.quota_month = v_month then v_state.accepted_count else 0 end;
  if v_state.lease_until > v_now or v_state.next_allowed_at > v_now then
    return jsonb_build_object('allowed', false, 'reason', 'busy', 'retry_after',
      greatest(1, ceil(extract(epoch from
        (greatest(v_state.lease_until, v_state.next_allowed_at) - v_now)))::integer));
  end if;
  if v_count >= p_monthly_limit then
    return jsonb_build_object('allowed', false, 'reason', 'quota', 'retry_after', 3600);
  end if;
  update public.oss_runtime_state set quota_month = v_month, accepted_count = v_count + 1,
    lease_token = p_token, lease_until = v_now + make_interval(secs => p_lease_seconds),
    next_allowed_at = v_now + make_interval(secs => p_interval_seconds)
  where id = 1;
  return jsonb_build_object('allowed', true);
end;
$$;

create or replace function public.oss_finish_analysis(
  p_token uuid, p_http_status integer, p_duration_seconds double precision
) returns jsonb
language plpgsql security invoker set search_path = '' as $$
begin
  if p_http_status is null or p_http_status not between 100 and 599
     or p_duration_seconds is null or not (p_duration_seconds between 0 and 100000) then
    raise exception 'Invalid timing';
  end if;
  update public.oss_runtime_state set lease_token = null, lease_until = '-infinity',
    success_count = success_count + case when p_http_status = 200 then 1 else 0 end,
    failure_count = failure_count + case when p_http_status = 200 then 0 else 1 end,
    success_seconds = success_seconds + case when p_http_status = 200 then p_duration_seconds else 0 end,
    failure_seconds = failure_seconds + case when p_http_status = 200 then 0 else p_duration_seconds end
  where id = 1 and lease_token = p_token;
  return jsonb_build_object('released', found);
end;
$$;

revoke all on function public.oss_claim_analysis(uuid, integer, integer, integer) from public, anon, authenticated;
revoke all on function public.oss_finish_analysis(uuid, integer, double precision) from public, anon, authenticated;
grant execute on function public.oss_claim_analysis(uuid, integer, integer, integer) to service_role;
grant execute on function public.oss_finish_analysis(uuid, integer, double precision) to service_role;
notify pgrst, 'reload schema';
commit;

-- Operator-only inspection; execute in SQL Editor, never publish as a browser API.
select quota_month, accepted_count, success_count, failure_count,
  (success_seconds + failure_seconds) / nullif(success_count + failure_count, 0) as average_seconds,
  success_seconds / nullif(success_count, 0) as average_success_seconds,
  failure_seconds / nullif(failure_count, 0) as average_failure_seconds
from public.oss_runtime_state where id = 1;
