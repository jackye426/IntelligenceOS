import assert from 'node:assert/strict';
// Deliberately limited to this repository's unquoted public DDL convention.
// Runtime catalog assertions in grants.test.mjs complement this source check.
export function checkSource(sql, contract) {
 const source=sql.replace(/--[^\n]*/g,'');
 const tables=[...source.matchAll(/CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?(\w+)\s*\(/gi)].map(x=>x[1]);
 for(const name of tables) {
  assert.equal(contract[name]?.kind,'table',`Declare grant contract for ${name}`);
  assert.match(source,new RegExp(`ALTER\\s+TABLE\\s+(?:public\\.)?${name}\\s+ENABLE\\s+ROW\\s+LEVEL\\s+SECURITY`,'i'),`Enable RLS for ${name}`);
  const expected=contract[name].privileges.join(', ');
  assert.match(source,new RegExp(`GRANT\\s+${expected}\\s+ON\\s+TABLE\\s+public\\.${name}\\s+TO\\s+service_role\\s*;`,'i'),`Explicit operations for ${name}`);
 }
 assert.doesNotMatch(source,/GRANT\s+ALL\b/i,'Do not restore blanket privileges');
 assert.doesNotMatch(source,/GRANT\s+[^;]+\s+TO\s+[^;]*\b(?:anon|authenticated|public)\b/i,'Do not restore browser-role privileges');
 return tables;
}
