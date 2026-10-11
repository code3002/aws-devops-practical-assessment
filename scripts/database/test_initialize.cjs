const { test } = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const { verifier, initialize } = require('./initialize.cjs');
const password = crypto.randomBytes(32).toString('base64url');
function client(unsafe = false) {
  return { calls: [], async query(sql) {
    this.calls.push(sql);
    return { rows: sql.startsWith('SELECT rolsuper') && unsafe ? [{ rolsuper: true }] : [] };
  } };
}
test('SCRAM verifier is valid and contains no plaintext password', () => {
  const value = verifier(password);
  assert.match(value, /^SCRAM-SHA-256\$4096:[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+:[A-Za-z0-9+/=]+$/);
  assert.ok(!value.includes(password));
  const [salt, keys] = value.slice('SCRAM-SHA-256$4096:'.length).split('$');
  const salted = crypto.pbkdf2Sync(password, Buffer.from(salt, 'base64'), 4096, 32, 'sha256');
  const clientKey = crypto.createHmac('sha256', salted).update('Client Key').digest();
  assert.equal(keys.split(':')[0], crypto.createHash('sha256').update(clientKey).digest('base64'));
});
test('initialization uses a transaction and can repeat without destructive SQL', async () => {
  const db = client();
  await initialize(db, password); await initialize(db, password);
  assert.equal(db.calls.filter(c => c === 'COMMIT').length, 2);
  assert.equal(db.calls.filter(c => c.includes('pg_advisory_xact_lock')).length, 2);
  assert.ok(db.calls.every(c => !c.includes(password)));
  assert.ok(db.calls.some(c => c.includes('IF NOT EXISTS')));
  assert.ok(db.calls.every(c => !/DROP |TRUNCATE |DELETE FROM/i.test(c)));
});
test('unsafe preexisting administrator role is rejected and rolled back', async () => {
  const db = client(true);
  await assert.rejects(initialize(db, password), /initialization failed/);
  assert.equal(db.calls.at(-1), 'ROLLBACK');
  assert.ok(!db.calls.some(c => c.startsWith('ALTER ROLE')));
});
test('application grants match read/write queries with sequence usage only', () => {
  const sql = fs.readFileSync(__dirname + '/initialize.sql', 'utf8');
  assert.ok(sql.includes('GRANT INSERT (text)'));
  assert.ok(sql.includes('GRANT SELECT ON TABLE'));
  assert.ok(sql.includes('GRANT USAGE ON SEQUENCE'));
  assert.ok(!/GRANT (ALL|UPDATE|DELETE|CREATE)|GRANT .*WITH GRANT OPTION/.test(sql));
  assert.ok(sql.includes('REVOKE ALL ON SCHEMA public FROM PUBLIC'));
});
test('initialization failure returns a generic error and rolls back', async () => {
  const db = client(); const base = db.query;
  db.query = async function(sql) { if (sql.startsWith('ALTER ROLE')) throw new Error(password); return base.call(this, sql); };
  await assert.rejects(initialize(db, password), e => !e.message.includes(password));
  assert.equal(db.calls.at(-1), 'ROLLBACK');
});

test('existing role memberships and object ownership are rejected', async () => {
  for (const prefix of ['SELECT 1 FROM pg_auth_members', 'SELECT 1 FROM pg_shdepend']) {
    const db = client(); const base = db.query;
    db.query = async function(sql) {
      if (sql.startsWith(prefix)) { this.calls.push(sql); return { rows: [{ unsafe: true }] }; }
      return base.call(this, sql);
    };
    await assert.rejects(initialize(db, password), /initialization failed/);
    assert.equal(db.calls.at(-1), 'ROLLBACK');
    assert.ok(!db.calls.some(c => c.startsWith('ALTER ROLE')));
  }
});
