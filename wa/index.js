// WhatsApp bridge (Baileys). Thin by design: connects, sends, forwards incoming group text.
// All decisions live in the Python API. Listens on 127.0.0.1 only.
//
//   GET  /status   → { state, qr (data URL), me, since }
//   GET  /groups   → [{ jid, subject, size }]
//   POST /send     { jid, text, quote?: { id, from_me, participant } } → { id }
//   POST /logout   → unlink this device; a new QR follows
//
// Incoming group messages → POST {API_URL}/api/wa/inbound

import crypto from 'node:crypto'
import fs from 'node:fs'
import http from 'node:http'
import makeWASocket, { Browsers, DisconnectReason, fetchLatestBaileysVersion, useMultiFileAuthState } from 'baileys'
import pino from 'pino'
import QRCode from 'qrcode'

const PORT = Number(process.env.WA_PORT || 3001)
const API_URL = process.env.API_URL || 'http://127.0.0.1:8000'
const SESSION_DIR = process.env.WA_SESSION_DIR || '/data/wa_session'
const TOKEN = crypto.createHash('sha256').update(`${process.env.PADDY_SECRET || 'dev-secret-change-me'}:wa`).digest('hex')
const log = (...a) => console.log(new Date().toISOString(), '[wa]', ...a)

let sock = null
let state = 'connecting' // connecting | qr | open | closed
let qr = null
let since = null
let retry = 0
const sentIds = new Set() // our own sends, so their echoes are ignored

function remember(id) {
  if (!id) return
  sentIds.add(id)
  if (sentIds.size > 5000) sentIds.delete(sentIds.values().next().value)
}

async function connect() {
  fs.mkdirSync(SESSION_DIR, { recursive: true })
  const { state: auth, saveCreds } = await useMultiFileAuthState(SESSION_DIR)
  const { version } = await fetchLatestBaileysVersion().catch(() => ({ version: undefined }))
  sock = makeWASocket({
    version, auth, logger: pino({ level: 'warn' }),
    browser: Browsers.ubuntu('Dayalbagh Truck Tracking'),
    markOnlineOnConnect: false, syncFullHistory: false, generateHighQualityLinkPreview: false,
  })
  sock.ev.on('creds.update', saveCreds)

  sock.ev.on('connection.update', async ({ connection, lastDisconnect, qr: code }) => {
    if (code) {
      state = 'qr'
      qr = await QRCode.toDataURL(code, { margin: 1, width: 280 })
      log('scan the QR in Admin → WhatsApp')
    }
    if (connection === 'open') {
      state = 'open'; qr = null; retry = 0; since = new Date().toISOString()
      log('connected as', sock.user?.id)
    }
    if (connection === 'close') {
      const code = lastDisconnect?.error?.output?.statusCode
      state = 'closed'
      if (code === DisconnectReason.loggedOut) {
        log('logged out — clearing session, new QR follows')
        fs.rmSync(SESSION_DIR, { recursive: true, force: true })
        setTimeout(connect, 1000)
      } else {
        const delay = Math.min(1000 * 2 ** retry++, 60000)
        log(`connection closed (${code}), retrying in ${delay}ms`)
        setTimeout(connect, delay)
      }
    }
  })

  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return
    for (const m of messages) {
      const jid = m.key.remoteJid || ''
      if (!jid.endsWith('@g.us') || sentIds.has(m.key.id)) continue
      const msg = m.message || {}
      const text = (msg.conversation || msg.extendedTextMessage?.text || '').trim()
      if (!text) continue
      const body = {
        id: m.key.id, jid, from_me: !!m.key.fromMe, me: sock.user?.id || '',
        sender: m.key.participant || '', sender_alt: m.key.participantAlt || '',
        push_name: m.pushName || '', text,
        ts: Number(m.messageTimestamp || Date.now() / 1000),
        quoted_id: msg.extendedTextMessage?.contextInfo?.stanzaId || null,
      }
      try {
        const r = await fetch(`${API_URL}/api/wa/inbound`, {
          method: 'POST', headers: { 'content-type': 'application/json', 'x-wa-token': TOKEN }, body: JSON.stringify(body),
        })
        if (!r.ok) log('inbound rejected', r.status, await r.text())
      } catch (e) {
        log('inbound failed', e.message)
      }
    }
  })
}

// ── local HTTP API ──────────────────────────────────────────────────────────

function reply(res, code, data) {
  res.writeHead(code, { 'content-type': 'application/json' })
  res.end(JSON.stringify(data))
}

async function readJson(req) {
  let s = ''
  for await (const chunk of req) s += chunk
  return s ? JSON.parse(s) : {}
}

http.createServer(async (req, res) => {
  if (req.headers['x-wa-token'] !== TOKEN) return reply(res, 401, { error: 'bad token' })
  try {
    if (req.method === 'GET' && req.url === '/status') {
      return reply(res, 200, { state, qr, since, me: sock?.user ? { id: sock.user.id, name: sock.user.name || '' } : null })
    }
    if (state !== 'open' && req.url !== '/logout') return reply(res, 503, { error: `WhatsApp ${state}` })

    if (req.method === 'GET' && req.url === '/groups') {
      const groups = await Promise.race([
        sock.groupFetchAllParticipating(),
        new Promise((_, rej) => setTimeout(() => rej(new Error('timeout listing groups')), 15000)),
      ])
      return reply(res, 200, Object.values(groups)
        .map((g) => ({ jid: g.id, subject: g.subject, size: g.participants?.length || 0 }))
        .sort((a, b) => a.subject.localeCompare(b.subject)))
    }
    if (req.method === 'POST' && req.url === '/send') {
      const { jid, text, quote } = await readJson(req)
      const opts = quote?.id
        ? { quoted: { key: { remoteJid: jid, id: quote.id, fromMe: !!quote.from_me, participant: quote.participant || undefined },
                      message: { conversation: quote.text || '' } } }
        : {}
      const sent = await sock.sendMessage(jid, { text }, opts)
      remember(sent?.key?.id)
      return reply(res, 200, { id: sent?.key?.id || null })
    }
    if (req.method === 'POST' && req.url === '/logout') {
      try { await sock?.logout() } catch { /* already gone */ }
      fs.rmSync(SESSION_DIR, { recursive: true, force: true })
      state = 'connecting'; qr = null; since = null
      setTimeout(connect, 1000)
      return reply(res, 200, { ok: true })
    }
    reply(res, 404, { error: 'not found' })
  } catch (e) {
    log('error', req.url, e.message)
    reply(res, 500, { error: e.message })
  }
}).listen(PORT, '127.0.0.1', () => log(`bridge on 127.0.0.1:${PORT}`))

connect().catch((e) => { log('fatal', e); process.exit(1) })
