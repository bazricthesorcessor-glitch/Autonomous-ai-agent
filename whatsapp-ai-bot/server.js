const { default: makeWASocket, useMultiFileAuthState, fetchLatestBaileysVersion, DisconnectReason } = require("@whiskeysockets/baileys")
const P       = require("pino")
const QRCode  = require("qrcode")
const http    = require("http")
const express = require("express")
const { Server } = require("socket.io")
const axios   = require("axios")
const fs      = require("fs")
const path    = require("path")

const app    = express()
const server = http.createServer(app)
const io     = new Server(server)
app.use(express.static(__dirname))

const AVRIL_CHAT_JID = process.env.AVRIL_CHAT_JID || "120363407032482808@g.us"

// ── LOOP PROTECTION ───────────────────────────────────────────────────────────
const SENT_IDS_FILE = path.join(__dirname, "..", "ai-model", "memory", "last_messages.json")
const SENT_IDS_MAX  = 200

function _loadSentIds() {
    try {
        return new Set(JSON.parse(fs.readFileSync(SENT_IDS_FILE, "utf8")).ids || [])
    } catch { return new Set() }
}
function _saveSentIds(set) {
    try {
        const tmp = SENT_IDS_FILE + ".tmp"
        fs.writeFileSync(tmp, JSON.stringify({ ids: [...set].slice(-SENT_IDS_MAX) }), "utf8")
        fs.renameSync(tmp, SENT_IDS_FILE)
    } catch (e) { console.warn("Could not save sent IDs:", e.message) }
}
const sentMessageIds = _loadSentIds()

// ── BRAIN ─────────────────────────────────────────────────────────────────────
async function askAvril(text) {
    try {
        const res = await axios.post(
            "http://localhost:8000/chat",
            { message: text },
            { timeout: 120000 }
        )
        return res.data.response || "..."
    } catch (err) {
        if (err.code === "ECONNABORTED") return "Thoda busy hoon, ek minute."
        console.error("[Brain]", err.message)
        return "Brain offline hai abhi."
    }
}

// ── WHATSAPP ──────────────────────────────────────────────────────────────────
let sock
let _reconnecting = false

async function startWhatsApp() {
    const { state, saveCreds } = await useMultiFileAuthState("auth_info")
    const { version }          = await fetchLatestBaileysVersion()

    sock = makeWASocket({
        version,
        auth:   state,
        logger: P({ level: "silent" }),
    })

    sock.ev.on("creds.update", saveCreds)

    sock.ev.on("connection.update", async ({ connection, qr, lastDisconnect }) => {
        if (qr) {
            console.log("Scan QR at http://localhost:3000")
            io.emit("qr", await QRCode.toDataURL(qr))
        }
        if (connection === "open") {
            console.log("✅ WhatsApp connected →", AVRIL_CHAT_JID)
            io.emit("status", "connected")
        }
        if (connection === "close") {
            const loggedOut = lastDisconnect?.error?.output?.statusCode === DisconnectReason.loggedOut
            if (loggedOut) {
                console.log("Logged out — scan QR again.")
                io.emit("status", "logged_out")
            } else if (!_reconnecting) {
                _reconnecting = true
                console.log("Reconnecting in 3s...")
                setTimeout(() => { _reconnecting = false; startWhatsApp() }, 3000)
            }
        }
    })

    // ALL upsert events — no type filter
    sock.ev.on("messages.upsert", async ({ messages, type }) => {
        console.log(`[upsert] type=${type} count=${messages.length}`)

        for (const msg of messages) {
            const jid = msg.key?.remoteJid
            const fromMe = msg.key?.fromMe
            const id  = msg.key?.id

            console.log(`  → jid=${jid} fromMe=${fromMe} id=${id?.slice(0,8)}`)

            // Echo protection
            if (sentMessageIds.has(id)) {
                sentMessageIds.delete(id)
                console.log("  → skipped (echo)")
                continue
            }

            // Only our chat
            if (jid !== AVRIL_CHAT_JID) {
                console.log(`  → skipped (jid mismatch: ${jid})`)
                continue
            }

            if (!msg.message) {
                console.log("  → skipped (no message body)")
                continue
            }

            // Extract text — all possible locations
            const text =
                msg.message.conversation ||
                msg.message.extendedTextMessage?.text ||
                msg.message.imageMessage?.caption ||
                msg.message.videoMessage?.caption ||
                (msg.message.audioMessage || msg.message.pttMessage ? "[Voice note]" : null) ||
                (msg.message.documentMessage ? `[Document: ${msg.message.documentMessage.fileName || "unknown"}]` : null)

            if (!text) {
                console.log("  → skipped (no text extracted), keys:", Object.keys(msg.message))
                continue
            }

            console.log(`📩  ${text}`)

            const reply = await askAvril(text)
            console.log(`💬  ${reply}`)

            try {
                const sent = await sock.sendMessage(AVRIL_CHAT_JID, { text: reply })
                if (sent?.key?.id) {
                    sentMessageIds.add(sent.key.id)
                    _saveSentIds(sentMessageIds)
                }
            } catch (e) {
                console.error("Send failed:", e.message)
            }
        }
    })
}

io.on("connection", (socket) => {
    if (sock?.user) socket.emit("status", "connected")
})

startWhatsApp()

server.listen(3000, () => {
    console.log("Avril WhatsApp → http://localhost:3000")
    console.log("Locked to:", AVRIL_CHAT_JID)
})