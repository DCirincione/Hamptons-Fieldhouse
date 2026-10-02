// Run with PGLITE_PATH pointing to a temporary @electric-sql/pglite install.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {randomUUID} from 'node:crypto';
const location = process.env.PGLITE_PATH;
if (!location) throw new Error('Set PGLITE_PATH to an installed @electric-sql/pglite directory');
const {PGlite} = await import(pathToFileURL(resolve(location, 'dist/index.js')));
const {btree_gist} = await import(pathToFileURL(resolve(location, 'dist/contrib/btree_gist.js')));
const db = new PGlite({extensions: {btree_gist}});
await db.exec('create role anon; create role authenticated; create role service_role; create schema extensions;');
for (const file of ['202609260003_bookings.sql','202610010001_rental_options.sql','202610010002_pricing_and_packages.sql','202610010003_booking_calendar.sql','202610010004_staff_schedule.sql']) {
  await db.exec(await readFile(new URL(`../supabase/migrations/${file}`, import.meta.url), 'utf8'));
}
const scalar = async (sql, params=[]) => (await db.query(sql, params)).rows[0].result;
const expectCode = async (fn, code) => {
  try { await fn(); assert.fail(`Expected ${code}`); }
  catch (error) { assert.equal(error.code, code, error.message); }
};
const dates = (await db.query("select ((now() at time zone 'America/New_York')::date + 2)::text as day, date_trunc('month', (now() at time zone 'America/New_York')::date + 2)::date::text as month")).rows[0];
const at = hour => scalar("select (($1::date + make_time($2::integer,0,0)) at time zone 'America/New_York')::text as result", [dates.day, hour]);
const availability = slug => scalar('select public.booking_availability($1, $2::date) as result', [slug, dates.month]);
const reserve = payload => scalar('select public.reserve_booking($1::jsonb) as result', [JSON.stringify(payload)]);
const review = (id, action) => scalar('select public.review_booking($1::uuid, $2) as result', [id, action]);
const make = async (service, hour, extra={}) => ({request_id:randomUUID(),service, starts_at:await at(hour), first_name:'Test',last_name:'Customer',email:'test@example.com',phone_number:'6315550123', party_size:12,extra_pizzas:0,own_food:false,payment_method:'venmo',notes:'',expected_total_cents:service==='full-field'?20000:service==='speed-agility'?7500:service==='turf-fun-party'?44500:54500,...extra});
const hasSlot = (data, at) => data.slots.some(slot => new Date(slot.starts_at).getTime() === new Date(at).getTime());
await expectCode(() => availability('full-field'), '55000');
await db.exec('update public.booking_policy set enabled = true;');
let available = await availability('full-field');
assert(hasSlot(available, await at(6)));
assert(hasSlot(available, await at(22)));
assert(!hasSlot(available, await at(23)));
assert(!hasSlot(await availability('turf-fun-party'), await at(22)));
assert(hasSlot(await availability('turf-fun-party'), await at(21)));
const payload = await make('turf-fun-party',10,{party_size:14,own_food:true,expected_total_cents:42900});
const party = await reserve(payload);
assert.equal(party.status, 'pending');
assert.equal(party.total_price_cents,42900);
assert.equal(party.payment_status, 'unpaid');
assert.equal((await reserve(payload)).reference,party.reference);
assert.equal(await scalar('select count(*)::integer as result from public.bookings'),1);
await expectCode(() => reserve({...payload,party_size:15}), '22023');
assert(!hasSlot(await availability('full-field'), await at(10)));
assert(hasSlot(await availability('full-field'), await at(11)), 'Field releases after 60 minutes');
assert(hasSlot(await availability('speed-agility'), await at(10)), 'Backspace is independent');
await expectCode(async () => reserve(await make('full-field',10)), 'P0002');
await expectCode(async () => reserve(await make('ultimate-field-house-party',10)), 'P0002');
await reserve(await make('speed-agility',10));
assert.equal((await review(party.reference,'approve')).status,'confirmed');
assert(!hasSlot(await availability('full-field'), await at(10)), 'Approved still blocks');
await review(party.reference,'cancel');
assert(hasSlot(await availability('full-field'), await at(10)), 'Cancellation releases field');
assert(!hasSlot(await availability('speed-agility'), await at(10)), 'Cancellation preserves unrelated bookings');
await expectCode(() => review(party.reference,'approve'), '22023');
await expectCode(async () => reserve(await make('full-field',12,{expected_total_cents:1})), 'P0003');
await expectCode(async () => reserve(await make('full-field',12,{own_food:true})), '22023');
await expectCode(async () => reserve(await make('full-field',12,{starts_at:'2020-01-01T10:00:00-05:00'})), '22023');
const pizzaParty = await reserve(await make('ultimate-field-house-party',13,{party_size:18, extra_pizzas:2,expected_total_cents:62300}));
assert.equal(pizzaParty.total_price_cents,62300);
assert.equal(await scalar('select count(*)::integer as result from public.booking_line_items where booking_id = $1',[pizzaParty.reference]),2);
// Blackout blocks the relevant resource, with no customer information exposed.
await db.query("insert into public.booking_resource_slots(resource,during,note) values ('field',tstzrange($1::timestamptz,$1::timestamptz+interval '1 hour','[)'),'Maintenance')",[await at(16)]);
assert(!hasSlot(await availability('full-field'),await at(16)));
await expectCode(async () => db.query("insert into public.booking_resource_slots(resource,during) values ('field',tstzrange($1::timestamptz,$1::timestamptz+interval '1 hour','[)'))",[await at(16)]),'23P01');
// Adjacent endpoints are permitted; overlap across both party packages is not.
await reserve(await make('full-field',14));
const day = (await availability('full-field'));
assert(!JSON.stringify(day).includes('test@example.com'));
assert(!JSON.stringify(day).includes('Customer'));
// Verify public roles cannot execute writes or read private data.
for (const role of ['anon','authenticated']) {
  await db.exec(`set role ${role};`);
  await expectCode(() => db.query('select * from public.bookings'),'42501');
  await expectCode(() => db.query('select * from public.booking_resource_slots'),'42501');
  await expectCode(() => reserve(payload),'42501');
  await expectCode(() => availability('full-field'),'42501');
  await db.exec('reset role;');
}
// Database rejects overlap even if an application bypasses the availability query.
await expectCode(async () => db.query("insert into public.booking_resource_slots(resource,during) values ('backspace',tstzrange($1::timestamptz,$1::timestamptz+interval '30 minutes','[)'))",[await at(10)]),'23P01');
// Staff series reserve availability atomically and are safe to retry.
const block = request => scalar('select public.add_schedule_blocks($1::jsonb) as result',[JSON.stringify(request)]);
const schedule = () => scalar('select public.staff_schedule($1::date) as result',[dates.month]);
const release = (id, series=false) => scalar('select public.remove_schedule_block($1::uuid,$2::boolean) as result',[id,series]);
const recurring = {request_id:randomUUID(),title:'Regular team',resources:['field','backspace'],occurrences:[
  {starts_at:await at(18),ends_at:await at(19)}, {starts_at:await at(20),ends_at:await at(21)}]};
const saved = await block(recurring);
assert.equal(saved.occurrences,2);
assert.equal((await block(recurring)).series_id,saved.series_id);
assert(!hasSlot(await availability('full-field'),await at(18)));
assert(!hasSlot(await availability('speed-agility'),await at(18)));
let blocks = (await schedule()).filter(row => row.series_id === saved.series_id);
assert.equal(blocks.length,4);
assert.equal((await release(blocks[0].id)).removed,2);
assert(hasSlot(await availability('full-field'),await at(18)));
blocks = (await schedule()).filter(row => row.series_id === saved.series_id);
assert.equal(blocks.length,2);
assert.equal((await release(blocks[0].id,true)).removed,2);
assert(hasSlot(await availability('full-field'),await at(20)));
await block(recurring); // Retrying a removed series must not resurrect its blocks.
assert.equal((await schedule()).filter(row => row.series_id === saved.series_id).length,0);
// A later conflicting occurrence rolls back even earlier free occurrences.
const conflict = {request_id:randomUUID(),title:'Conflicting series',resources:['field'],occurrences:[
  {starts_at:await at(18),ends_at:await at(19)}, {starts_at:await at(16),ends_at:await at(17)}]};
await expectCode(() => block(conflict),'23P01');
assert(hasSlot(await availability('full-field'),await at(18)));
assert.equal(await scalar('select count(*)::integer as result from public.booking_block_series where id=$1',[conflict.request_id]),0);
const bookingSlot=(await schedule()).find(row => row.booking_id);
await expectCode(() => release(bookingSlot.id,true),'22023');
for (const role of ['anon','authenticated']) {
  await db.exec(`set role ${role};`);
  await expectCode(() => block(recurring),'42501');
  await expectCode(() => schedule(),'42501');
  await expectCode(() => release(bookingSlot.id),'42501');
  await db.exec('reset role;');
}
await db.close();
console.log('Database checks passed: migrations, hours, pending holds, independent spaces, party resource split, extras/discounts, price tampering, idempotency, approval/cancellation, blackout overlap constraints, and public access denied.');
