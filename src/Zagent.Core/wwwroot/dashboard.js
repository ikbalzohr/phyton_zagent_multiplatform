'use strict';
const base = '/api/management/v1/';
// Match only the static administrator hint; never display upstream exception/title/detail text.
const profileDependencyHint = 'Use authenticated local-owner diagnostics with this request ID to check owner profile authorization, private management connectivity, and catalog validation. This response does not identify the failed check or prove Files is stopped. Do not bypass authorization. For uncertain mutations, retain the same payload and idempotency key.';
let csrf, profileRevision, page = '', generation = 0, timer, busy = false;
const $ = id => document.getElementById(id);
const node = (tag, text) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = String(text); return n; };
const display = value => value == null ? 'unknown' : typeof value === 'object' ? JSON.stringify(value) : String(value);
const visualMetadata = (value) => value ? { source: value.source, label: value.label, mimeType: value.mimeType, bytes: value.bytes, capturedAtUtc: value.capturedAtUtc } : null;
async function request(path, options = {}) {
  const response = await fetch(path.startsWith('/') ? path : base + path, { credentials: 'same-origin', cache: 'no-store', ...options });
  if (response.status === 401) { location.assign('/Login'); throw new Error('Session expired'); }
  if (!response.ok) {
    const failure = await response.json().catch(() => null);
    const code = typeof failure?.code === 'string' && /^[A-Z0-9_]{1,80}$/.test(failure.code) ? ` ${failure.code}` : '';
    const requestId = typeof failure?.requestId === 'string' && /^[A-Za-z0-9_.:-]{1,128}$/.test(failure.requestId) ? ` Request ID: ${failure.requestId}.` : '';
    const hint = failure?.hint === profileDependencyHint ? ` ${profileDependencyHint}` : '';
    const error = new Error(`Request unavailable (${response.status})${code}; no success is assumed.${requestId}${hint}`); error.status = response.status; throw error;
  }
  return response.status === 204 ? null : response.json();
}
async function mutate(path, body, method = 'POST') {
  if (!csrf) csrf = (await request('csrf')).token;
  return request(path, { method, headers: { 'Content-Type': 'application/json', 'X-CSRF-TOKEN': csrf,
    'Idempotency-Key': crypto.randomUUID(), ...(profileRevision ? { 'If-Match': profileRevision } : {}) }, body: body === undefined ? undefined : JSON.stringify(body) });
}
function notice(text, error = false) { $('notice').textContent = text; $('notice').classList.toggle('error', error); }
function button(label, action, danger = false) {
  const b = node('button', label); b.type = 'button'; if (danger) b.className = 'danger';
  b.addEventListener('click', async () => { b.disabled = true; try { await action(); } catch (e) { if (!e.profileUncertain) notice(e.message, true); } finally { b.disabled = false; } }); return b;
}
function table(target, rows, fields, actions) {
  target.replaceChildren();
  if (!rows?.length) { target.append(node('p', 'No records in the current bounded snapshot.')); return; }
  const wrapper = node('div'); wrapper.className = 'table-scroll'; const t = node('table'), head = node('tr');
  fields.forEach(f => head.append(node('th', f))); if (actions) head.append(node('th', 'Actions')); t.append(head);
  rows.slice(0, 200).forEach(row => { const tr = node('tr'); fields.forEach(f => tr.append(node('td', display(row[f]))));
    if (actions) { const td = node('td'); actions(row).forEach(b => td.append(b)); tr.append(td); } t.append(tr); });
  wrapper.append(t); target.append(wrapper);
}
function record(target, data) {
  const dl = node('dl'); dl.className = 'record';
  Object.entries(data || {}).forEach(([key, value]) => { dl.append(node('dt', key), node('dd', display(value))); }); target.replaceChildren(dl);
}
async function command(path, body, method) {
  const result = await mutate(path, body, method);
  if (!result.operationId) { notice(result.message || 'Request acknowledged.'); return; }
  notice(`Operation ${result.operationId}: ${result.state}. Request disconnect does not cancel it.`);
  // Poll the SAME operation ID; never replay the command on missing response or unknown outcome.
  for (let n = 0; n < 45; n++) {
    await new Promise(resolve => setTimeout(resolve, 1000));
    const op = await request('operations/' + encodeURIComponent(result.operationId));
    notice(`Operation ${op.operationId}: ${op.state}${op.method === 'task.cancel' && op.state === 'succeeded' ? ' — cancel requested; refresh job state to confirm.' : ''}`, ['failed','unknown','conflict'].includes(op.state));
    if (!['accepted', 'running'].includes(op.state)) { await refresh(); return; }
  }
  notice('Operation still pending. Do not replay it; inspect its operation ID later.', true);
}
let pendingProfileCommand;
async function profileCommand(path, body, method = 'POST') {
  if (pendingProfileCommand) {
    notice('Resolve the previous uncertain profile command before submitting another.', true);
    $('notice').append(button('Retry exact command', sendProfileCommand));
    const error = new Error('Previous profile outcome unresolved.'); error.profileUncertain = true; throw error;
  }
  pendingProfileCommand = { path, body: JSON.stringify(body), method, key: crypto.randomUUID(), revision: profileRevision };
  return sendProfileCommand();
}
async function sendProfileCommand() {
  const cmd = pendingProfileCommand;
  try {
    if (!csrf) csrf = (await request('csrf')).token;
    const result = await request(cmd.path, { method: cmd.method, headers: {
      'Content-Type': 'application/json', 'X-CSRF-TOKEN': csrf, 'Idempotency-Key': cmd.key, 'If-Match': cmd.revision
    }, body: cmd.body });
    if (result.status !== 'committed' || result.access_sync !== 'committed') throw new Error('No committed backend outcome.');
    pendingProfileCommand = null; notice(`Profile committed · access synchronized · revision ${result.revision}`); await refresh();
  } catch (error) {
    if ([400,403,409,428,429].includes(error.status)) { pendingProfileCommand = null; await refresh(); throw error; }
    notice(error.message + ' Outcome not assumed. Same actor/key/payload is retained.', true);
    $('notice').append(button('Retry exact command', sendProfileCommand));
    error.profileUncertain = true;
    throw error;
  }
}
function profileEditor(row, target) {
  if (target.querySelector('form')) { notice('Resolve the current edit before starting another.', true); return; }
  const form = node('form'); form.className = 'form-row';
  const root = node('input'); root.value = row.root; root.required = true;
  const mode = node('select'); ['read-only','read-write'].forEach(value => { const option = node('option',value); option.value = value; mode.append(option); }); mode.value = row.mode;
  const enabled = node('input'); enabled.type = 'checkbox'; enabled.checked = row.enabled;
  const description = node('input'); description.value = row.description || ''; description.maxLength = 512;
  [['Root',root],['Mode',mode],['Enabled',enabled],['Description',description]].forEach(([text,input]) => { const label = node('label',text); label.append(input); form.append(label); });
  form.append(button('Save profile', async () => { await profileCommand('workspaces/profiles/' + encodeURIComponent(row.name),
    { changes: { root: root.value, mode: mode.value, enabled: enabled.checked, description: description.value } }, 'PUT'); form.remove(); }));
  form.append(button('Cancel edit', () => form.remove()));
  form.addEventListener('submit', e => e.preventDefault());
  return form;
}
const data = async path => (await request(path)).data;
async function render(current, stamp) {
  // Fetch everything needed for a page before touching DOM; old-page requests cannot overwrite a newer page.
  const apply = fn => { if (stamp === generation && current === page) fn(); };
  if (current === 'overview') { const d = await data('overview'); apply(() => record($('overview-content'), d)); }
  if (current === 'agents') {
    const [agents, capabilities] = await Promise.all([data('agents'), data('capabilities')]);
    apply(() => { table($('agents-content'), agents, ['agentId','version','health','processState','processTreeOwned','lastError'], row =>
      ['start','stop','restart','refresh'].map(operation => button(operation, () => command('agents/' + encodeURIComponent(row.agentId) + '/actions', { operation }), operation === 'stop')));
      table($('capabilities-content'), capabilities, ['agentId','capability','access','execution','supportsCancel','supportsResume']); });
  }
  if (current === 'workspaces') {
    const d = await data('workspaces'); apply(() => {
      profileRevision = d.revision;
      const target = $('workspaces-content'); target.replaceChildren(node('p', `Workspace: ${d.workspaceId} · default profile: ${d.defaultProfile} · unavailable dependencies: ${display(d.unavailableDependencies)}`));
      const profiles = node('div'); target.append(profiles);
      table(profiles, d.profiles, ['name','root','mode','enabled','description','authorized_by_user'], row => [
        button('Edit', () => { const editor = profileEditor(row, target); if (!editor) return; target.append(editor); editor.querySelector('input').focus(); }),
        button('Set default', () => profileCommand('workspaces/profiles/' + encodeURIComponent(row.name) + '/default', {})),
        button('Remove', async () => { let replacement_default_id;
          if (row.name === d.defaultProfile) { replacement_default_id = prompt('Exact replacement default profile ID (required)', ''); if (!replacement_default_id) return; }
          await profileCommand('workspaces/profiles/' + encodeURIComponent(row.name), replacement_default_id ? { replacement_default_id } : {}, 'DELETE'); }, true)]);
      target.append(node('h2','Action approvals')); const approvals = node('div'); target.append(approvals);
      table(approvals, d.pendingApprovals, ['requestId','kind','source','status','summary'], row => row.source === 'Files' && row.canResolveLocally ?
        ['approve','deny'].map(action => button(action, async () => { if (confirm(`${action} this exact Files request?`)) await command('approvals/' + encodeURIComponent(row.requestId) + '/decision', { requestId: row.requestId, action, source: 'Files' }); })) : [node('span','Use the owning agent consent UI; no dashboard grant.')]);
    });
  }
  if (current === 'connections') { const [d, routes] = await Promise.all([data('connections'), data('routes')]); apply(() => { record($('connections-content'), d); table($('routes-content'), routes.services, ['name','namespace','agentStatus','mcpStatus','routing','tools','lastError']); }); }
  if (current === 'jobs') { const d = await data('jobs'); apply(() => table($('jobs-content'), d.tasks, ['taskId','principalId','workspaceId','agent','tool','state','progress','stopMode'], row => row.canStop ? [button('Request cancel', () => command('jobs/' + encodeURIComponent(row.taskId) + '/cancel', {}), true)] : [])); }
  if (current === 'artifacts') { const visual = await request('visuals').catch(() => ({ available: false })); const d = await request('artifacts'); apply(() => { record($('artifacts-content'), { latest: visualMetadata(visual), download: d.available ? d.contentUrl : null }); if (d.available && d.contentUrl?.startsWith(base + 'artifacts/')) { const a = node('a', 'Download verified artifact'); a.href = d.contentUrl; a.download = ''; $('artifacts-content').append(a); } }); }
  if (current === 'logs') { const d = await request('logs'); apply(() => table($('logs-content'), d.technical, ['timestampUtc','level','source','event','message'])); }
  if (current === 'settings') { const d = await request('settings'); apply(() => record($('settings-content'), d)); }
}
async function refresh() {
  if (busy || document.hidden) return;
  if (page === 'workspaces' && $('workspaces-content').querySelector('form')) { clearTimeout(timer); timer = setTimeout(refresh, 3000); return; }
  busy = true; const current = page, stamp = generation;
  try { await render(current, stamp); if (stamp === generation) { $('freshness').textContent = `Last successful response: ${new Date().toLocaleTimeString()} · bounded polling · installation scope`; $('freshness').classList.remove('offline'); } }
  catch (e) { if (stamp === generation) { $('freshness').textContent = 'OFFLINE / UNAVAILABLE — previous data is stale. ' + e.message; $('freshness').classList.add('offline'); } }
  finally { busy = false; clearTimeout(timer); timer = setTimeout(refresh, $('freshness').classList.contains('offline') ? 10000 : 3000); }
}
function navigate() {
  const allowed = ['overview','agents','workspaces','connections','jobs','artifacts','logs','settings'];
  page = allowed.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'overview'; generation++;
  document.querySelectorAll('.page').forEach(s => { s.hidden = s.id !== page; });
  document.querySelectorAll('nav a').forEach(a => a.classList.toggle('active', a.hash === '#' + page));
  $('heading').textContent = document.querySelector(`nav a[href="#${page}"]`).textContent;
  $('freshness').textContent = 'Refreshing; no current snapshot yet…'; clearTimeout(timer); refresh();
}
document.querySelectorAll('[data-runtime]').forEach(b => b.addEventListener('click', () => { if (confirm(`Request ${b.dataset.runtime}?`)) command('runtime/actions', { operation: b.dataset.runtime }).catch(e => notice(e.message, true)); }));
document.querySelectorAll('[data-integration]').forEach(b => b.addEventListener('click', () => command('connections/actions', { action: b.dataset.integration }).catch(e => notice(e.message, true))));
$('shutdown').addEventListener('click', async () => { if (prompt('Stops agents and the dashboard. Type STOP CORE to confirm.') !== 'STOP CORE') return; try { await command('runtime/shutdown', { confirmation: 'STOP CORE' }); clearTimeout(timer); } catch (e) { notice('Shutdown response unavailable. Do not assume success: ' + e.message, true); } });
$('logout').addEventListener('click', async () => { try { await mutate('/auth/logout', {}); location.assign('/Login'); } catch (e) { notice(e.message, true); } });
$('profile-form').addEventListener('submit', async e => { e.preventDefault(); try {
  const values = Object.fromEntries(new FormData(e.target)); values.enabled = e.target.elements.enabled.checked;
  await profileCommand('workspaces/profiles', values); e.target.reset();
} catch (err) { if (!err.profileUncertain) notice(err.message, true); } });
$('workflow-form').addEventListener('submit', async e => { e.preventDefault(); const values = Object.fromEntries(new FormData(e.target));
  try { const path = values.runId ? 'workflows/' + encodeURIComponent(values.runId) + '/evidence' : 'workflows'; const result = await request(path + '?principalId=' + encodeURIComponent(values.principalId)); record($('workflows-content'), result); }
  catch (err) { notice(err.message, true); } });
addEventListener('hashchange', navigate); document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); }); navigate();
