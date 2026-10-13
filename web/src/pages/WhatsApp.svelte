<script>
  import { onDestroy } from 'svelte'
  import Icon from '../lib/Icon.svelte'
  import Modal from '../lib/Modal.svelte'
  import Toggle from '../lib/Toggle.svelte'
  import { api, dateTime, time } from '../lib/api.js'
  import { toast } from '../lib/stores.svelte.js'

  let st = $state(null) // { status, outbox, failed, activity }
  let settings = $state(null)
  let groups = $state([])
  let groupsError = $state('')
  let unlinkOpen = $state(false)

  async function load() {
    try {
      ;[st, settings] = await Promise.all([api.get('/api/admin/wa'), settings ? settings : api.get('/api/admin/settings')])
      if (st.status.state === 'open' && !groups.length && !groupsError) loadGroups()
    } catch (e) { toast(e.message, 'warn') }
  }
  async function loadGroups() {
    groupsError = ''
    try { groups = await api.get('/api/admin/wa/groups') } catch (e) { groupsError = e.message }
  }
  load()
  const timer = setInterval(load, 3000) // QR rotates; activity is live
  onDestroy(() => clearInterval(timer))

  async function set(key, value, msg) {
    const prev = settings[key]
    settings[key] = value
    try {
      settings = await api.put('/api/admin/settings', { [key]: value })
      if (msg) toast(msg)
    } catch (e) {
      settings[key] = prev
      toast(e.message, 'warn')
    }
  }
  const on = (k) => settings?.[k] === '1'
  const bool = (k, msgOn, msgOff) => (v) => set(k, v ? '1' : '0', v ? msgOn : msgOff)

  async function test(target) {
    try { await api.post('/api/admin/wa/test', { target }); toast(`Test sent to ${target} group`) } catch (e) { toast(e.message, 'warn') }
  }
  async function summaryNow() {
    try { await api.post('/api/admin/wa/summary'); toast('Summary queued') } catch (e) { toast(e.message, 'warn') }
  }
  async function unlink() {
    unlinkOpen = false
    try { await api.post('/api/admin/wa/logout'); groups = []; toast('Unlinked — scan the new QR') } catch (e) { toast(e.message, 'warn') }
  }

  const state = $derived(st?.status?.state || 'offline')
  const STATE = { open: ['live', 'Connected'], qr: ['warn', 'Scan QR to link'], connecting: ['idle', 'Connecting…'],
                  closed: ['warn', 'Reconnecting…'], offline: ['warn', 'Bridge offline'] }
  const groupName = (jid) => groups.find((g) => g.jid === jid)?.subject || (jid === settings?.fleet_jid ? 'Fleet' : jid === settings?.control_jid ? 'Control' : jid)
  const phone = $derived(st?.status?.me?.id ? '+' + st.status.me.id.split(/[:@]/)[0] : '')
</script>

{#if st && settings}
  <div class="wa">
    <section class="card status">
      <div class="card-h">
        <h3>Connection</h3>
        <span class="pill {STATE[state]?.[0] || 'idle'}">{STATE[state]?.[1] || state}</span>
      </div>
      <div class="card-b">
        {#if state === 'open'}
          <p class="linked"><span class="mono">{phone}</span>{#if st.status.me?.name} · {st.status.me.name}{/if}</p>
          <p class="mute small">Linked {st.status.since ? `since ${dateTime(st.status.since)}` : ''}. Messages are sent from this number.</p>
          <div class="row"><button class="btn quiet sm danger" onclick={() => (unlinkOpen = true)}>Unlink device</button></div>
        {:else if state === 'qr' && st.status.qr}
          <div class="qr">
            <img src={st.status.qr} alt="WhatsApp link QR code" width="220" height="220" />
            <ol>
              <li>Open WhatsApp on the phone that will send the messages</li>
              <li>Settings → Linked devices → Link a device</li>
              <li>Scan this code. It refreshes by itself.</li>
            </ol>
          </div>
        {:else if state === 'offline'}
          <p class="notice">The WhatsApp bridge isn't running. {st.status.error || ''}</p>
        {:else}
          <p class="mute">Waiting for WhatsApp…</p>
        {/if}
      </div>
    </section>

    <section class="card master" class:off={!on('wa_enabled')}>
      <div class="card-b">
        <Toggle checked={on('wa_enabled')} label="WhatsApp {on('wa_enabled') ? 'on' : 'off'}"
          hint={on('wa_enabled') ? 'Relaying reports, reading groups, sending summaries.' : 'Nothing is sent or read. Reports made while off are not sent later.'}
          onchange={bool('wa_enabled', 'WhatsApp on', 'WhatsApp off')} />
      </div>
    </section>

    <section class="card">
      <div class="card-h">
        <h3>Groups</h3>
        <button class="btn ghost sm" onclick={loadGroups} disabled={state !== 'open'}><Icon name="refresh" size={14} />Refresh list</button>
      </div>
      <div class="card-b groups">
        {#if groupsError}<p class="notice err">{groupsError}</p>{/if}
        {#each [['fleet_jid', 'Fleet group', 'Operators post events here. Web reports are relayed here.', 'fleet'],
                ['control_jid', 'Control group', 'Shift start/end, summaries, questions and confirmations.', 'control']] as [key, label, hint, target]}
          <div class="group">
            <div class="text"><b>{label}</b><span>{hint}</span></div>
            <div class="row">
              <select class="select sm grow" value={settings[key]} onchange={(e) => set(key, e.target.value, `${label} set`)}>
                <option value="">Not set</option>
                {#if settings[key] && !groups.some((g) => g.jid === settings[key])}<option value={settings[key]}>{settings[key]}</option>{/if}
                {#each groups as g}<option value={g.jid}>{g.subject} · {g.size}</option>{/each}
              </select>
              <button class="btn quiet sm" disabled={!settings[key] || state !== 'open'} onclick={() => test(target)}>Test</button>
            </div>
          </div>
        {/each}
        {#if settings.fleet_jid && settings.fleet_jid === settings.control_jid}
          <p class="notice">Fleet and control are the same group — everything goes to one place.</p>
        {/if}
      </div>
    </section>

    <section class="card">
      <div class="card-h"><h3>Behaviour</h3></div>
      <div class="card-b">
        <Toggle checked={on('send_fleet')} label="Post in the fleet group"
          hint={on('send_fleet') ? 'Off = the fleet group is never written to; everything goes to control. Reading still works.' : 'Nothing is posted in the fleet group. Relays, confirmations, edits and summaries go to control only.'}
          onchange={bool('send_fleet', 'Posting in fleet group', 'Fleet group silenced')} />
        <Toggle checked={on('relay_fleet')} disabled={!on('send_fleet')} label="Relay web reports to the fleet group" onchange={bool('relay_fleet', 'Relaying to fleet', 'Not relaying to fleet')} />
        <Toggle checked={on('relay_control')} label="Relay web reports to the control group" onchange={bool('relay_control', 'Relaying to control', 'Not relaying to control')} />
        <Toggle checked={on('read_fleet')} label="Read the fleet group" hint="Typed messages like “A,B LS KN4” become reports; unclear ones get a short question."
          onchange={bool('read_fleet', 'Reading fleet group', 'Ignoring fleet group')} />
        <Toggle checked={on('summary_on_shift_end')} label="Summary when a shift ends" onchange={bool('summary_on_shift_end', 'End-of-shift summary on', 'End-of-shift summary off')} />

        <div class="modes">
          {#each [['silent', 'Silent fleet group', 'Fleet group only gets relayed reports. Confirmations, questions and summaries go to control.'],
                  ['full', 'Full', 'Confirmations reply in the fleet group; summaries are posted there too.']] as [v, t, d]}
            <button class="mode" class:on={settings.fleet_mode === v} disabled={!on('send_fleet')} onclick={() => set('fleet_mode', v, `${t} mode`)}>
              <b>{t}</b><span>{d}</span>
            </button>
          {/each}
        </div>

        <div class="two">
          <label class="field"><span>Summary every (minutes, 0 = off)</span>
            <input class="input" type="number" min="0" value={settings.summary_interval_min}
              onchange={(e) => set('summary_interval_min', e.target.value, 'Summary interval saved')} /></label>
          <label class="field"><span>Warn when a shift runs longer than (hours)</span>
            <input class="input" type="number" min="1" value={settings.shift_stale_hours}
              onchange={(e) => set('shift_stale_hours', e.target.value, 'Saved')} /></label>
        </div>
        <div class="row end"><button class="btn quiet sm" onclick={summaryNow} disabled={!on('wa_enabled')}>Send summary now</button></div>
      </div>
    </section>

    <section class="card activity">
      <div class="card-h">
        <h3>Activity</h3>
        <span class="row">
          {#each Object.entries(st.outbox) as [k, n]}<span class="pill plain {k === 'failed' ? 'warn' : k === 'pending' ? 'live' : ''}">{n} {k}</span>{/each}
        </span>
      </div>
      {#each st.failed as f}<p class="notice err fail">#{f.id} {f.kind}: {f.error}</p>{/each}
      <ul>
        {#each st.activity as a (a.id)}
          <li class={a.direction}>
            <span class="dir" title={a.direction === 'in' ? 'received' : 'sent'}>{a.direction === 'in' ? '←' : '→'}</span>
            <span class="mono when">{time(a.at)}</span>
            <span class="where">{groupName(a.jid)}</span>
            <span class="kind pill plain">{a.kind}</span>
            <span class="body mono">{a.text}</span>
          </li>
        {:else}
          <li class="mute">No messages yet.</li>
        {/each}
      </ul>
    </section>
  </div>

  <Modal bind:open={unlinkOpen} title="Unlink WhatsApp?">
    <p>This number stops sending and reading. You'll need to scan a new QR code to link again.</p>
    {#snippet actions()}
      <button class="btn ghost" onclick={() => (unlinkOpen = false)}>Cancel</button>
      <button class="btn signal" onclick={unlink}>Unlink</button>
    {/snippet}
  </Modal>
{/if}

<style>
  .wa { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; align-items: start; }
  .activity { grid-column: 1 / -1; }
  .small { font-size: 12.5px; }
  .linked { font-size: 18px; font-weight: 600; margin-bottom: 4px; }
  .row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
  .row.end { justify-content: flex-end; }
  .card-h .row { margin: 0; }

  .qr { display: flex; gap: 20px; align-items: center; flex-wrap: wrap; }
  .qr img { border-radius: 12px; box-shadow: inset 0 0 0 1px var(--hair); background: #fff; padding: 6px; }
  .qr ol { margin: 0; padding-left: 18px; font-size: 13.5px; color: var(--ink-2); display: flex; flex-direction: column; gap: 6px; flex: 1; min-width: 180px; }

  .master { grid-column: 2; grid-row: 1; }
  .master.off { box-shadow: inset 0 0 0 1.5px var(--signal), var(--shadow); }
  .master .card-b { padding-top: 6px; padding-bottom: 6px; }

  .groups { display: flex; flex-direction: column; gap: 16px; }
  .group .text { display: flex; flex-direction: column; gap: 2px; }
  .group .text b { font-size: 14px; }
  .group .text span { font-size: 12.5px; color: var(--mute); }
  .group .row { margin-top: 8px; }
  .group select { min-width: 0; }

  .modes { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 14px 0; }
  .mode { text-align: left; display: flex; flex-direction: column; gap: 4px; padding: 12px; border-radius: var(--r); box-shadow: inset 0 0 0 1px var(--hair); transition: box-shadow .15s, background .15s; }
  .mode b { font-size: 13.5px; }
  .mode span { font-size: 12px; color: var(--mute); }
  .mode.on { box-shadow: inset 0 0 0 1.5px var(--ink); background: var(--surface); }
  .mode:disabled { opacity: .45; }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }

  .fail { margin: 0 16px 8px; }
  .activity ul { list-style: none; margin: 0; padding: 0 0 6px; max-height: 420px; overflow-y: auto; }
  .activity li {
    display: grid; grid-template-columns: 18px 44px 90px 70px 1fr; gap: 10px; align-items: baseline;
    padding: 8px 16px; border-top: 1px solid var(--hair-2); font-size: 13px;
  }
  .dir { font-weight: 700; color: var(--mute); }
  .out .dir { color: var(--signal); }
  .when { font-size: 11.5px; color: var(--mute); }
  .where { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ink-2); }
  .kind { justify-self: start; }
  .body { white-space: pre-wrap; font-size: 12px; color: var(--ink); }

  @media (max-width: 1000px) {
    .wa { grid-template-columns: minmax(0, 1fr); }
    .master { grid-column: auto; grid-row: auto; }
  }
  @media (max-width: 640px) {
    .modes, .two { grid-template-columns: 1fr; }
    .activity li { grid-template-columns: 16px 40px 1fr; }
    .kind { display: none; }
    .body { grid-column: 2 / -1; }
  }
</style>
