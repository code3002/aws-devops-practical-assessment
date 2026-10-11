// Optional real PostgreSQL test driver; input contains generated local-test secrets only.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { Client } = require('/app/node_modules/pg');
const { initialize, verifier } = require('./initialize.cjs');
async function main() {
  let text = ''; for await (const chunk of process.stdin) text += chunk;
  const config = JSON.parse(text);
  const connection = { host: 'testpg', database: 'assessment', ssl: { rejectUnauthorized: true, servername: 'testpg', ca: fs.readFileSync('/certs/rds-ca.pem', 'utf8') } };
  const root = new Client({ ...connection, user: 'fixture_root', password: config.rootPassword });
  const admin = new Client({ ...connection, user: 'assessment_admin', password: config.adminPassword });
  const app = new Client({ ...connection, user: 'assessment_app', password: config.appPassword });
  try {
    await root.connect();
    for (const invalidConfig of [{ host: 'wrong-host', ssl: { ...connection.ssl, servername: 'wrong-host' } }, { ssl: { ...connection.ssl, ca: '' } }]) {
      const invalid = new Client({ ...connection, ...invalidConfig, user: 'fixture_root', password: config.rootPassword });
      try { await assert.rejects(invalid.connect(), error => ['ERR_TLS_CERT_ALTNAME_INVALID', 'SELF_SIGNED_CERT_IN_CHAIN', 'DEPTH_ZERO_SELF_SIGNED_CERT', 'UNABLE_TO_VERIFY_LEAF_SIGNATURE'].includes(error.code)); }
      finally { await invalid.end(); }
    }
    await root.query(`CREATE ROLE assessment_admin LOGIN CREATEDB CREATEROLE PASSWORD '${verifier(config.adminPassword)}'`);
    await root.query('ALTER DATABASE assessment OWNER TO assessment_admin');
    await admin.connect();
    const query = admin.query.bind(admin);
    let failPassword = true;
    admin.query = async (...args) => {
      try {
        if (failPassword && args[0].startsWith('ALTER ROLE assessment_app PASSWORD')) { failPassword = false; await query('SELECT 1/0'); }
        return await query(...args);
      }
      catch (error) { console.error('Administrator statement rejected: ' + args[0].split(/\s+/)[0] + ' ' + error.code); throw error; }
    };
    await assert.rejects(initialize(admin, config.appPassword), /initialization failed/);
    assert.equal((await root.query("SELECT count(*)::int AS count FROM pg_roles WHERE rolname='assessment_app'")).rows[0].count, 0);
    assert.equal((await root.query("SELECT to_regclass('public.messages') AS relation")).rows[0].relation, null);
    await initialize(admin, config.appPassword);
    await app.connect();
    const row = await app.query('INSERT INTO messages (text) VALUES ($1) RETURNING id', ['Preserve this row']);
    await initialize(admin, config.appPassword);
    const saved = await app.query('SELECT id, text FROM messages WHERE id = $1', [row.rows[0].id]);
    assert.equal(saved.rows[0].text, 'Preserve this row');
    for (const sql of ["UPDATE messages SET text = 'denied'", 'DELETE FROM messages', 'TRUNCATE messages',
      'CREATE TABLE public.forbidden (id int)', 'CREATE ROLE forbidden', 'CREATE DATABASE forbidden',
      "INSERT INTO messages (id,text) VALUES (99999,'denied')", "SELECT setval('messages_id_seq',99999)"]) {
      await assert.rejects(app.query(sql), error => error.code === '42501');
    }
    const flags = await root.query("SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname='assessment_app'");
    assert.ok(Object.values(flags.rows[0]).every(value => value === false));
    await root.query('ALTER ROLE assessment_app CREATEDB');
    await assert.rejects(initialize(admin, config.appPassword), /initialization failed/);
    await root.query('ALTER ROLE assessment_app NOCREATEDB');
    await root.query('CREATE ROLE fixture_extra');
    await root.query('GRANT fixture_extra TO assessment_app');
    await assert.rejects(initialize(admin, config.appPassword), /initialization failed/);
    await root.query('REVOKE fixture_extra FROM assessment_app');
    await root.query('ALTER TABLE messages OWNER TO assessment_app');
    await assert.rejects(initialize(admin, config.appPassword), /initialization failed/);
    await root.query('ALTER TABLE messages OWNER TO assessment_admin');
    await initialize(admin, config.appPassword);
    assert.equal((await app.query('SELECT count(*)::int AS count FROM messages')).rows[0].count, 1);
    console.log('PASS: non-superuser initialization, repeat/data preservation, insert/read, eight privilege denials, role/membership/ownership rejection, atomic failure rollback, TLS positive/negative checks');
  } finally {
    await app.end(); await admin.end(); await root.end();
  }
}
main().catch(error => { console.error('Integration test failed: ' + (error.code || error.name)); process.exitCode = 1; });
