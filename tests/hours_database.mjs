// PGLITE_PATH: temporary @electric-sql/pglite install; BOOKING_SCHEMA_DIR:
// externally managed baseline SQL, before availability_hours.sql is applied.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {randomUUID} from 'node:crypto';
const {PGlite} = await import(pathToFileURL(resolve(process.env.PGLITE_PATH, 'dist/index.js')));
const {btree_gist} = await import(pathToFileURL(resolve(process.env.PGLITE_PATH, 'dist/contrib/btree_gist.js')));
const db = new PGlite({extensions:{btree_gist}});
await db.exec('create role anon; create role authenticated; create role service_role; create schema extensions;');
for (const name of ['202609260003_bookings.sql','202610010001_rental_options.sql','202610010002_pricing_and_packages.sql','202610010003_booking_calendar.sql']) {
  await db.exec(await readFile(resolve(process.env.BOOKING_SCHEMA_DIR, name), 'utf8'));
}
await db.exec(await readFile(new URL('../scripts/sql/availability_hours.sql', import.meta.url), 'utf8'));
// Reproduce an installation with the hours update but missing older staff tables.
const repair = await readFile(new URL('../scripts/sql/repair_manual_blocks.sql', import.meta.url), 'utf8');
await db.exec(repair);
await db.exec(repair); // Idempotent repair must preserve existing schema.
await db.exec('update public.booking_policy set enabled = true;');
const scalar = async (sql, params = []) => (await db.query(sql, params)).rows[0].result;
const errorCode = async (fn, code) => { try { await fn(); assert.fail(`Expected ${code}`); } catch (error) { assert.equal(error.code, code, error.message); } };
const target = (await db.query("select ((now() at time zone 'America/New_York')::date + 2)::text as day, date_trunc('month', (now() at time zone 'America/New_York')::date + 2)::date::text as month")).rows[0];
const at = time => scalar("select (($1::date + $2::time) at time zone 'America/New_York')::text as result", [target.day, time]);
const availability = (slug = 'full-field') => scalar('select public.booking_availability($1, $2::date) as result', [slug, target.month]);
const has = (data, start) => data.slots.some(slot => Date.parse(slot.starts_at) === Date.parse(start));
const weekly = days => scalar('select public.set_weekly_opening_hours($1::jsonb) as result', [JSON.stringify(days)]);
const override = value => scalar('select public.set_date_opening_hours($1::jsonb) as result', [JSON.stringify({date:target.day,...value})]);
const days = Array.from({length:7}, (_, weekday) => ({weekday, opens:'08:00', closes:'20:30'}));
const makeBooking = async time => ({request_id:randomUUID(),service:'full-field',starts_at:await at(time),first_name:'Test',last_name:'Member',email:'test@example.com',phone_number:'6315550123',party_size:1,extra_pizzas:0,own_food:false,payment_method:'venmo',notes:'',expected_total_cents:20000});
const reserve = payload => scalar('select public.reserve_booking($1::jsonb) as result', [JSON.stringify(payload)]);
assert(has(await availability(), await at('06:00')));
await weekly(days);
assert(!has(await availability(), await at('07:00')));
assert(has(await availability(), await at('08:00')));
assert(has(await availability(), await at('19:00')));
assert(!has(await availability(), await at('20:00')));
assert(has(await availability('turf-fun-party'), await at('19:00')));
const existing = await reserve(await makeBooking('09:00'));
await override({opens:null,closes:null});
assert(!(await availability()).slots.some(slot => slot.starts_at.slice(0,10) === target.day));
await errorCode(async () => reserve(await makeBooking('10:00')), 'P0002');
assert.equal(await scalar('select status as result from public.bookings where id = $1', [existing.reference]), 'pending');
await weekly(days.map(day => ({...day,opens:'04:00'})));
assert(!has(await availability(), await at('04:00'))); // Date closure wins over weekly edits.
await override({reset:true});
assert(has(await availability(), await at('04:00')));
const request = {request_id:randomUUID(),title:'Early team',resources:['field'],occurrences:[{starts_at:await at('04:00'),ends_at:await at('05:00')}]};
await scalar('select public.add_schedule_blocks($1::jsonb) as result', [JSON.stringify(request)]);
assert(!has(await availability(), await at('04:00')));
await override({opens:'11:30',closes:'14:30'});
assert(!has(await availability(), await at('11:00')));
assert(has(await availability(), await at('12:00')));
assert(has(await availability('turf-fun-party'), await at('13:00')));
assert(!has(await availability(), await at('14:00')));
await errorCode(() => weekly(days.slice(0,6)), '22023');
await errorCode(() => weekly(days.map(day => ({...day,opens:'22:00',closes:'08:00'}))), '23514');
const saved = await scalar('select public.staff_opening_hours() as result');
assert(saved.days.every(day => day.opens === '04:00:00')); // Invalid update rolled back atomically.
assert.equal(saved.overrides[0].opens, '11:30:00');
await db.exec('set role authenticated;');
await errorCode(() => scalar('select public.staff_opening_hours() as result'), '42501');
await errorCode(() => weekly(days), '42501');
await db.exec('reset role;');
await db.close();
console.log('Database checks passed: migration, default/weekly/date hours, closures, resets, duration boundaries, stale reservation rejection, retained bookings, early staff blocks, atomic validation, private RPC permissions.');
