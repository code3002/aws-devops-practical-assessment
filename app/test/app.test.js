import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createApp } from '../app.js';
async function withApp(db, run) {
 const server = createApp(db).listen(0, '127.0.0.1');
 await new Promise(resolve => server.once('listening', resolve));
 try { await run(`http://127.0.0.1:${server.address().port}`); } finally { await new Promise(resolve => server.close(resolve)); }
}
test('clock, JSON time, health and 404', async () => withApp({}, async base => {
 const page = await (await fetch(base + '/?text=%3Cscript%3E')).text();
 assert.match(page, /id="clock"/); assert.match(page, /\d{4}-\d{2}-\d{2}T/); assert.ok(!page.includes('<script>'));
 const first = await (await fetch(base+'/time')).json(); assert.ok(Number.isFinite(Date.parse(first.timestamp)));
 const js = await (await fetch(base+'/clock.js')).text(); assert.match(js, /setInterval/); assert.match(js, /textContent/);
 assert.equal((await fetch(base+'/health')).status,200); assert.equal((await fetch(base+'/missing')).status,404);
}));
test('database write/read uses parameters and JSON-safe output', async () => {
 const calls=[]; const text = "<script>alert(1)</script>'; DROP TABLE messages;--";
 await withApp({ query: async (sql, args) => {calls.push([sql,args]); return {rows: calls.length===1 ? [{id:1}] : [{id:1,text}]};}}, async base => {
 const r=await fetch(base+'/messages',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})});
 assert.equal(r.status,201); assert.match(r.headers.get('content-type'),/application\/json/); assert.equal((await r.json()).text,text);
 });
 assert.deepEqual(calls[0][1],[text]); assert.deepEqual(calls[1][1],[1]); assert.ok(calls.every(([sql])=>!sql.includes(text)));
});
test('invalid input and database failure do not expose internals', async () => withApp({query:async()=>{throw new Error('secret-password');}}, async base => {
 const post = text => fetch(base+'/messages',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})});
 assert.equal((await post('')).status,400);
 const r=await post('valid'); assert.equal(r.status,503); assert.ok(!(await r.text()).includes('secret-password'));
}));

test('oversized JSON is rejected as 413', async () => withApp({}, async base => {
 const r = await fetch(base+'/messages', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:'x'.repeat(5000)})});
 assert.equal(r.status,413);
}));
