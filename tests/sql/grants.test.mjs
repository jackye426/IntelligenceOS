import { PGlite } from '@electric-sql/pglite';
import { vector } from '@electric-sql/pglite/vector';
import { readFileSync, readdirSync } from 'node:fs';
import assert from 'node:assert/strict';
import test from 'node:test';
import { checkSource } from './contract.mjs';
const root = new URL('../../', import.meta.url);
const contract = JSON.parse(readFileSync(new URL('./grant-contract.json', import.meta.url)));
const files = readdirSync(new URL('sql/', root)).filter(x => x.endsWith('.sql')).sort();

test('fresh SQL chain grants only the declared backend operations with automatic grants absent', async () => {
 const db = new PGlite({extensions:{vector}});
 try {
  await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
   GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
   CREATE TABLE public.integrated_practitioner_with_phin (id text PRIMARY KEY);
   CREATE TABLE public.integrated_practitioners (id uuid PRIMARY KEY DEFAULT gen_random_uuid());`);
  for (const file of files) {
   try { await db.exec(readFileSync(new URL('sql/'+file,root),'utf8')); }
   catch(e) { throw new Error(`${file}: ${e.message}`, {cause:e}); }
   // Check access at each file boundary, not just after a later file repairs it.
   for(const [name,spec] of Object.entries(contract)) {
    if(spec.kind==='external' && file<'016') continue;
    const {rows}=await db.query('SELECT to_regclass($1) AS oid',[`public.${name}`]);
    if(!rows[0].oid) continue;
    for(const op of spec.privileges) {
     const result=await db.query('SELECT has_table_privilege($1,$2,$3) AS permitted',['service_role',`public.${name}`,op]);
     assert.equal(result.rows[0].permitted,true,`${file}: service_role ${op} ${name}`);
    }
   }
  }
  const objects = await db.query(`SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','S') ORDER BY c.relname`);
  assert.deepEqual(objects.rows.map(x=>x.relname), [...Object.keys(contract),'integrated_practitioner_with_phin'].sort(),
    'Every created table/view/sequence must have a reviewed grant contract (external FK fixture excluded)');
  await db.exec(`SET ROLE service_role;
   INSERT INTO clinic_accounts (id,name,website_url) VALUES ('00000000-0000-0000-0000-000000000001','Synthetic test clinic','https://example.invalid') RETURNING id;
   UPDATE clinic_accounts SET name='Synthetic updated' WHERE id='00000000-0000-0000-0000-000000000001' RETURNING id;
   INSERT INTO document_embeddings(entity_type,entity_id,content) VALUES ('clinic_account','00000000-0000-0000-0000-000000000001','synthetic fixture') RETURNING id;
   DELETE FROM document_embeddings WHERE entity_id='00000000-0000-0000-0000-000000000001'; RESET ROLE;`);
  for(const role of ['anon','authenticated']) {
   await db.exec(`SET ROLE ${role}`);
   await assert.rejects(db.query('SELECT * FROM clinic_accounts'),/permission denied/);
   await assert.rejects(db.query('INSERT INTO clinic_accounts(name,website_url) VALUES (\'denied\',\'https://example.invalid\')'),/permission denied/);
   await db.exec('RESET ROLE');
  }
  for(const [name,spec] of Object.entries(contract)) {
   for(const role of ['anon','authenticated','service_role']) {
    for(const op of ['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER','MAINTAIN']) {
     const {rows} = await db.query('SELECT has_table_privilege($1,$2,$3) AS permitted',[role,`public.${name}`,op]);
     assert.equal(rows[0].permitted,role==='service_role' && spec.privileges.includes(op),`${role} ${op} ${name}`);
    }
   }
   if(spec.kind!=='view') {
    const {rows}=await db.query('SELECT relrowsecurity FROM pg_class WHERE oid=$1::regclass',[`public.${name}`]);
    assert.equal(rows[0].relrowsecurity,true,`RLS ${name}`);
   }
  }
 } finally {await db.close();}
});


test('every table creation carries an explicit reviewed contract, including future files', () => {
 const found=new Set();
 for(const file of files) for(const name of checkSource(readFileSync(new URL('sql/'+file,root),'utf8'),contract)) found.add(name);
 assert.deepEqual([...found].sort(),Object.keys(contract).filter(x=>contract[x].kind==='table').sort());
});

test('source guard rejects missing grants, missing RLS, undeclared tables and public/broad grants', () => {
 const valid='CREATE TABLE clinic_accounts (id uuid); ALTER TABLE public.clinic_accounts ENABLE ROW LEVEL SECURITY; GRANT SELECT, INSERT, UPDATE ON TABLE public.clinic_accounts TO service_role;';
 checkSource(valid,contract);
 for(const bad of [valid.replace(/GRANT[^;]+;/,''), valid.replace(/ALTER[^;]+;/,''),valid.replaceAll('clinic_accounts','new_unreviewed_table'),valid+' GRANT SELECT ON TABLE public.clinic_accounts TO anon;',valid+' GRANT ALL ON TABLE public.clinic_accounts TO service_role;']) {
  assert.throws(()=>checkSource(bad,contract));
 }
});
