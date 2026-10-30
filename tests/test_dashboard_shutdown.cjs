'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'src/Zagent.Core/wwwroot/dashboard.js'), 'utf8');
const markup = fs.readFileSync(path.join(root, 'src/Zagent.Core/Pages/Index.cshtml'), 'utf8');
assert.ok(source.includes('function bindShutdownDialog()'), 'missing shutdown dialog controller');
const controller = source.slice(source.indexOf('function bindShutdownDialog()'), source.indexOf("$('profile-form').addEventListener"));
const requestSource = source.slice(source.indexOf('async function request('), source.indexOf('async function mutate('));
const mutate = source.slice(source.indexOf('async function mutate('), source.indexOf('function notice('));
class Element {
  constructor() { this.listeners = {}; this.disabled = false; this.open = false; this.textContent = ''; this.classList = { add() {} }; }
  addEventListener(type, fn) { this.listeners[type] = fn; }
  async fire(type) { const event = { prevented: false, preventDefault() { this.prevented = true; } }; await this.listeners[type]?.(event); return event; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  focus() { this.focused = true; }
}
function fixture(reply = async () => ({state: 'accepted'}), httpStatus) {
  const ids = Object.fromEntries(['shutdown','shutdown-dialog','shutdown-confirm','shutdown-cancel','shutdown-status','freshness'].map(k => [k,new Element()]));
  const calls = [], notices = [], cleared = []; let refreshes = 0;
  const context = vm.createContext({
    $: id => ids[id], document: { querySelectorAll: () => Object.values(ids) }, csrf:'fixture-csrf', profileRevision:undefined,
    crypto:{randomUUID:()=>'fixture-key'}, shutdownPhase:'idle', generation:0, timer:17,
    clearTimeout:id=>cleared.push(id), refresh:()=>{ refreshes++; },
    notice:(text,error)=>notices.push({text,error}),
    base:'/api/management/v1/',
    fetch:async (url,options)=>{calls.push({url,options});return {status:httpStatus,ok:false,json:async()=>({})};},
    request:async (url, options)=>{ calls.push({url,options}); return reply(url,options); }
  });
  vm.runInContext((httpStatus ? requestSource : '') + mutate + controller,context);
  return {ids,calls,notices,cleared,context,get refreshes(){return refreshes;}};
}
(async () => {
  const cancel = fixture();
  await cancel.ids.shutdown.fire('click');
  assert.equal(cancel.ids['shutdown-dialog'].open,true); assert.equal(cancel.calls.length,0);
  assert.equal(cancel.ids['shutdown-cancel'].focused,true,'safe default focus is cancel');
  await cancel.ids['shutdown-cancel'].fire('click');
  assert.equal(cancel.ids['shutdown-dialog'].open,false); assert.equal(cancel.calls.length,0);
  await cancel.ids.shutdown.fire('click');
  assert.equal((await cancel.ids['shutdown-dialog'].fire('cancel')).prevented,false);
  assert.equal(cancel.calls.length,0,'Escape never submits');
  const accepted = fixture();
  await accepted.ids.shutdown.fire('click');
  await accepted.ids['shutdown-confirm'].fire('click');
  assert.equal(accepted.calls.length,1); assert.equal(accepted.calls[0].url,'runtime/shutdown');
  assert.equal(accepted.calls[0].options.headers['X-CSRF-TOKEN'],'fixture-csrf');
  assert.deepEqual(JSON.parse(accepted.calls[0].options.body),{confirmation:'STOP CORE'});
  assert.equal(accepted.context.shutdownPhase,'accepted');
  assert.equal(accepted.ids['shutdown-dialog'].open,false);
  assert.ok(accepted.notices.at(-1).text.includes('diterima'));
  assert.equal(accepted.refreshes,0,'no operation polling or refresh after shutdown acceptance');
  await accepted.ids['shutdown-confirm'].fire('click'); assert.equal(accepted.calls.length,1,'no duplicate dispatch');
  let release;
  const pending = fixture(()=>new Promise(resolve=>{release=resolve;}));
  await pending.ids.shutdown.fire('click'); const first = pending.ids['shutdown-confirm'].fire('click');
  assert.equal(pending.ids['shutdown-confirm'].disabled,true);
  assert.equal(pending.ids['shutdown-cancel'].disabled,true);
  assert.equal((await pending.ids['shutdown-dialog'].fire('cancel')).prevented,true);
  await pending.ids['shutdown-confirm'].fire('click'); assert.equal(pending.calls.length,1);
  release({state:'accepted'}); await first;
  const denied = fixture(async()=>{const e=new Error('SECRET');e.status=403;throw e;});
  await denied.ids.shutdown.fire('click'); await denied.ids['shutdown-confirm'].fire('click');
  assert.equal(denied.context.shutdownPhase,'idle'); assert.equal(denied.ids['shutdown-dialog'].open,true);
  assert.equal(denied.ids['shutdown-cancel'].disabled,false); assert.equal(denied.refreshes,1);
  const unauthenticated = fixture(undefined,401);
  await unauthenticated.ids.shutdown.fire('click'); await unauthenticated.ids['shutdown-confirm'].fire('click');
  assert.equal(unauthenticated.context.shutdownPhase,'idle','actual HTTP 401 is definitive rejection, not uncertain shutdown');
  assert.equal(unauthenticated.ids['shutdown-dialog'].open,true);
  assert.equal(unauthenticated.ids['shutdown-cancel'].disabled,false);
  assert.equal(unauthenticated.ids['shutdown-confirm'].disabled,false);
  assert.equal(unauthenticated.refreshes,1);
  assert.equal(unauthenticated.calls.length,1,'no automatic shutdown replay after 401');
  for (const reply of [async()=>{throw new Error('SECRET');},async()=>({state:'succeeded'})]) {
    const uncertain=fixture(reply); await uncertain.ids.shutdown.fire('click'); await uncertain.ids['shutdown-confirm'].fire('click');
    assert.equal(uncertain.context.shutdownPhase,'uncertain'); assert.equal(uncertain.calls.length,1);
    assert.equal(uncertain.refreshes,0); assert.equal(uncertain.notices.at(-1).error,true);
    assert.ok(!uncertain.notices.at(-1).text.includes('SECRET'));
    assert.ok(uncertain.notices.at(-1).text.includes('belum terkonfirmasi'));
  }
  assert.ok(markup.includes('<dialog id="shutdown-dialog"'));
  assert.ok(markup.includes('id="shutdown-cancel"') && markup.includes('Batalkan'));
  assert.ok(markup.includes('aria-labelledby="shutdown-title"'));
  assert.ok(!source.includes("prompt('Stops agents"),'no typed prompt remains');
  assert.match(source,/async function refresh\(\)\s*\{\s*if \(shutdownPhase !== 'idle'/,'refresh pauses after request');
  assert.ok(source.includes("if (shutdownPhase === 'idle') timer = setTimeout(refresh"),'in-flight refresh cannot reschedule after shutdown');
  assert.match(source,/function navigate\(\)\s*\{\s*if \(shutdownPhase !== 'idle'/,'navigation cannot restart polling');
  console.log('PASS shutdown dialog: open/cancel/Escape, CSRF, acceptance, pending double-click, denial, uncertainty and polling guards');
})().catch(error=>{console.error(error);process.exitCode=1;});
