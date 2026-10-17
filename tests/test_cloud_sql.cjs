// Run with @electric-sql/pglite installed, or set OSS_PGLITE_MODULE to its module directory.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { PGlite } = require(process.env.OSS_PGLITE_MODULE || '@electric-sql/pglite');

(async () => {
  const db = new PGlite();
  const sql = fs.readFileSync(path.join(__dirname, '../deploy/cloud-runtime.sql'), 'utf8');
  const first = '00000000-0000-0000-0000-000000000001';
  const second = '00000000-0000-0000-0000-000000000002';
  const asRole = async (role, query, parameters = []) => {
    await db.exec(`set role ${role}`);
    try { return await db.query(query, parameters); }
    finally { await db.exec('reset role'); }
  };
  const claim = async (token, limit = 1) => (await asRole('service_role',
    'select public.oss_claim_analysis($1::uuid, $2::integer, 30, 900) as result', [token, limit])).rows[0].result;
  const finish = async (token, status = 200) => (await asRole('service_role',
    'select public.oss_finish_analysis($1::uuid, $2::integer, 10) as result', [token, status])).rows[0].result;
  try {
    await db.exec('create role anon; create role authenticated; create role service_role bypassrls;');
    await db.exec(sql);
    for (const role of ['anon', 'authenticated']) {
      await assert.rejects(asRole(role, 'select * from public.oss_runtime_state'), /permission denied/);
      await assert.rejects(asRole(role,
        'select public.oss_claim_analysis($1::uuid, 1, 30, 900)', [first]), /permission denied/);
    }
    const guards = (await db.query(`select
      (select relrowsecurity from pg_class where oid = 'public.oss_runtime_state'::regclass) as rls,
      (select bool_and(not prosecdef) from pg_proc where proname in
        ('oss_claim_analysis', 'oss_finish_analysis')) as invoker`)).rows[0];
    assert.deepEqual(guards, { rls: true, invoker: true });
    assert.equal((await claim(first)).allowed, true);
    assert.equal((await claim(second)).reason, 'busy');
    assert.equal((await finish(second)).released, false);
    assert.equal((await finish(first)).released, true);
    assert.equal((await finish(first)).released, false); // no duplicate timing
    assert.equal((await claim(second)).reason, 'busy'); // cooldown survives release
    await db.exec("update public.oss_runtime_state set next_allowed_at = '-infinity'");
    assert.equal((await claim(second)).reason, 'quota');
    await db.exec(sql); // repeated setup must not reset quota or timing
    let state = (await db.query('select * from public.oss_runtime_state')).rows[0];
    assert.equal(state.accepted_count, 1);
    assert.equal(Number(state.success_count), 1);
    await db.exec("update public.oss_runtime_state set quota_month = '2000-01-01'");
    assert.equal((await claim(first)).allowed, true);
    await db.exec("update public.oss_runtime_state set lease_until = '-infinity', next_allowed_at = '-infinity'");
    assert.equal((await claim(second, 2)).allowed, true); // recover an interrupted worker's lease
    assert.equal((await finish(first)).released, false); // old worker cannot release a new lease
    assert.equal((await finish(second, 504)).released, true);
    state = (await db.query('select * from public.oss_runtime_state')).rows[0];
    assert.equal(state.accepted_count, 2);
    assert.equal(Number(state.failure_count), 1);
    assert.equal(state.success_seconds, 10);
    assert.equal(state.failure_seconds, 10);
    await assert.rejects(claim(first, 0), /Invalid analysis limits/);
    console.log('Cloud SQL checks passed: permissions, RLS, leases, cooldown, quota, rollover and timings.');
  } finally {
    await db.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
