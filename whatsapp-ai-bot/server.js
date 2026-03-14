const express = require("express")
const { default: makeWASocket, useMultiFileAuthState, fetchLatestBaileysVersion, DisconnectReason } = require("@whiskeysockets/baileys")
const P = require("pino")
const QRCode = require("qrcode")
const http = require("http")
const { Server } = require("socket.io")
const axios = require("axios")
const { default: PQueue } = require("p-queue")
const fs   = require("fs")
const path = require("path")

const app = express()
const server = http.createServer(app)
const io = new Server(server)

// ── AI REQUEST QUEUE ─────────────────────────────────────────────────────────
// Concurrency=2: two normal messages can be processed in parallel.
// !commands still bypass the queue entirely for instant response.
const aiQueue = new PQueue({ concurrency: 2 })

app.use(express.static(__dirname))

// ── OWNER SECURITY ──────────────────────────────────────────────────────────
// Set this to your WhatsApp number (country code + number, no +)
// Example: India number 9189XXXXXXXX → "918955574967@s.whatsapp.net"
// Leave empty ("") to disable the whitelist during initial setup.
const OWNER_JID = process.env.AVRIL_OWNER_JID || "918955574967@s.whatsapp.net"

let sock
let selectedChat   = null
let _reconnecting  = false   // Guard — prevents duplicate sockets on rapid close events

// --- STATE MANAGEMENT ---
const USER_COOLDOWN_MS =  1000; // 1 sec Rate Limit
const userMessageTracker = new Map();

// ── LOOP PROTECTION ───────────────────────────────────────────────────────────
// Persist sent message IDs so they survive restarts.
// WhatsApp replays recent messages on reconnect — without this the bot re-replies
// to its own old messages on every restart.
const SENT_IDS_FILE = path.join(__dirname, "..", "ai-model", "memory", "last_messages.json")
const SENT_IDS_MAX  = 200   // Keep at most this many IDs on disk

function _loadSentIds() {
    try {
        const data = JSON.parse(fs.readFileSync(SENT_IDS_FILE, "utf8"))
        return new Set(data.ids || [])
    } catch {
        return new Set()
    }
}

function _saveSentIds(set) {
    try {
        const ids = [...set].slice(-SENT_IDS_MAX)
        const tmp = SENT_IDS_FILE + ".tmp"
        fs.writeFileSync(tmp, JSON.stringify({ ids }), "utf8")
        fs.renameSync(tmp, SENT_IDS_FILE)   // atomic replace
    } catch (e) {
        console.warn("Could not persist sent IDs:", e.message)
    }
}

const sentMessageIds = _loadSentIds()

// ── NOTIFICATION & AUTO-REPLY STATE ──────────────────────────────────────────
// myRecentMessages: outgoing messages the user typed from their own phone (for tone)
// autoReplyChats:   chats where AI is replying on the user's behalf
// pendingReplies:   notifications waiting for the user to manually respond

const myRecentMessages = new Map()   // jid → string[]
const autoReplyChats   = new Map()   // jid → { until: number, toneMessages: string[] }
const pendingReplies   = new Map()   // msgId → { jid, text, name, senderJid, timer }

const MY_MSG_HISTORY   = 20
const AUTO_REPLY_MS    = 5 * 60 * 1000   // 5 minutes
const PENDING_REPLY_MS = 60 * 1000       // 60 s for user to reply manually

function buildTonePrompt(incomingText, senderName, autoInfo) {
    const examples = autoInfo.toneMessages.length > 0
        ? autoInfo.toneMessages.slice(-10).map((m, i) => `  ${i + 1}. "${m}"`).join('\n')
        : '  (No previous messages — use casual friendly style)'
    return (
        `You are replying in a WhatsApp chat on behalf of the user. Pretend you ARE the user.\n\n` +
        `The user's recent messages (learn their tone from these):\n${examples}\n\n` +
        `Reply to this message from ${senderName || 'the other person'}: "${incomingText}"\n\n` +
        `Rules:\n` +
        `- Match the user's exact style (length, punctuation, slang, emoji use if any)\n` +
        `- Be natural and conversational, never break character\n` +
        `- Do NOT reveal you are an AI\n` +
        `- Reply ONLY with the message text, nothing else`
    )
}
async function getAIResponse(text) {
    try {
        const response = await axios.post("http://localhost:8000/chat", {
            message: text
        })
        return response.data.response
    } catch (err) {
        console.error("Python Brain Error:", err.message)
        return "My brain (Python) is offline."
    }
}

async function startWhatsApp() {
    const { state, saveCreds } = await useMultiFileAuthState("auth_info")
    const { version } = await fetchLatestBaileysVersion()

    sock = makeWASocket({
        version,
        logger: P({ level: "debug" }),
                        auth: state
    })

    sock.ev.on("creds.update", saveCreds)

    sock.ev.on("connection.update", async (update) => {
        const { connection, qr, lastDisconnect } = update

        if (qr) {
            console.log("🔥 QR STRING RECEIVED!")
            const qrImage = await QRCode.toDataURL(qr)
            io.emit("qr", qrImage)
        }

        if (connection === "open") {
            console.log("✅ WhatsApp Connected Successfully!")
            io.emit("connected", "WhatsApp Connected Successfully!")
        }

        if (connection === "close") {
            const statusCode = lastDisconnect?.error?.output?.statusCode
            const loggedOut  = statusCode === DisconnectReason.loggedOut
            console.log(`❌ Connection closed. Status: ${statusCode ?? 'unknown'}`)

            if (loggedOut) {
                // Credential revoked — user must scan QR again
                console.log("🔒 Logged out — scan QR to reconnect.")
                io.emit("disconnected", "Logged out — please reconnect via QR.")
            } else if (!_reconnecting) {
                // Transient drop — reconnect once after a short delay
                _reconnecting = true
                console.log("↩  Reconnecting in 3 s...")
                setTimeout(() => { _reconnecting = false; startWhatsApp() }, 3000)
            }
        }
    })

    // --- MESSAGE HANDLER ---
    sock.ev.on("messages.upsert", async ({ messages }) => {
        const msg = messages[0]
        if (!msg.message) return

        // ── 0. Track user's own phone messages for tone analysis ──────────────
        const _rawText = msg.message.conversation || msg.message.extendedTextMessage?.text
        if (msg.key.fromMe && _rawText && !sentMessageIds.has(msg.key.id)) {
            const _jid = msg.key.remoteJid
            if (!myRecentMessages.has(_jid)) myRecentMessages.set(_jid, [])
            const _arr = myRecentMessages.get(_jid)
            _arr.push(_rawText)
            if (_arr.length > MY_MSG_HISTORY) _arr.shift()
        }

        // ── 1. Echo protection ────────────────────────────────────────────────
        if (sentMessageIds.has(msg.key.id)) {
            sentMessageIds.delete(msg.key.id)
            return
        }

        // ── 2. Ignore our own outgoing messages ───────────────────────────────
        if (msg.key.fromMe) return

        // ── 3. Extract text / media ───────────────────────────────────────────
        const textOnly =
            msg.message.conversation ||
            msg.message.extendedTextMessage?.text

        const imgMsg = msg.message.imageMessage
        const vidMsg = msg.message.videoMessage
        const audMsg = msg.message.audioMessage || msg.message.pttMessage
        const docMsg = msg.message.documentMessage
        const stkMsg = msg.message.stickerMessage

        let mediaNote = null
        if (imgMsg) mediaNote = imgMsg.caption  ? `[Image] ${imgMsg.caption}`  : "[Image received — no caption]"
        if (vidMsg) mediaNote = vidMsg.caption  ? `[Video] ${vidMsg.caption}`  : "[Video received — no caption]"
        if (audMsg) mediaNote = "[Voice note received — audio transcription not available]"
        if (docMsg) mediaNote = `[Document received: ${docMsg.fileName || docMsg.mimetype || "unknown"}]`
        if (stkMsg) mediaNote = "[Sticker received]"

        const text = textOnly || mediaNote
        if (!text) return

        const sender    = msg.key.remoteJid
        const senderJid = msg.key.participant || sender
        const name      = msg.pushName || senderJid.split('@')[0]

        // ── 4. Scope check ────────────────────────────────────────────────────
        if (!selectedChat || sender !== selectedChat) return

        // ── 5. Owner check ────────────────────────────────────────────────────
        if (OWNER_JID && senderJid !== OWNER_JID) {
            console.log(`Ignored non-owner message from: ${senderJid}`)
            return
        }

        // ── 6. Rate limiting ──────────────────────────────────────────────────
        const now           = Date.now()
        const lastReplyTime = userMessageTracker.get(senderJid)
        if (lastReplyTime && now - lastReplyTime < USER_COOLDOWN_MS) {
            console.log(`⛔ Rate limited: ${senderJid}`)
            return
        }

        console.log("\n--- 📩 INCOMING ---")
        console.log("From:", name, "→", text)

        // ── 7. Auto-reply mode ────────────────────────────────────────────────
        const autoInfo = autoReplyChats.get(sender)
        if (autoInfo && Date.now() < autoInfo.until) {
            const prompt    = buildTonePrompt(text, name, autoInfo)
            const aiResponse = await aiQueue.add(() => getAIResponse(prompt))
            try {
                const sentMsg = await sock.sendMessage(sender, { text: aiResponse })
                if (sentMsg?.key?.id) {
                    sentMessageIds.add(sentMsg.key.id)
                    _saveSentIds(sentMessageIds)
                }
                userMessageTracker.set(senderJid, now)
                io.emit("auto-reply-sent", { jid: sender, reply: aiResponse, name })
                console.log("🤖 Auto-replied:", aiResponse)
            } catch (e) { console.error("Auto-reply failed:", e) }
            return
        }

        // ── 8. Normal mode: notify UI, start 60s pending window ───────────────
        io.emit("incoming-message", { msgId: msg.key.id, jid: sender, name, text })

        const timer = setTimeout(async () => {
            // User didn't reply in time — fall back to default AI reply
            pendingReplies.delete(msg.key.id)
            io.emit("pending-expired", { msgId: msg.key.id })
            try {
                const aiResponse = text.startsWith('!')
                    ? await getAIResponse(text)
                    : await aiQueue.add(() => getAIResponse(text))
                const sentMsg = await sock.sendMessage(sender, { text: aiResponse })
                if (sentMsg?.key?.id) {
                    sentMessageIds.add(sentMsg.key.id)
                    _saveSentIds(sentMessageIds)
                }
                userMessageTracker.set(senderJid, now)
            } catch (e) { console.error("Timeout fallback reply failed:", e) }
        }, PENDING_REPLY_MS)

        pendingReplies.set(msg.key.id, { jid: sender, text, name, senderJid, timer })
        userMessageTracker.set(senderJid, now)
    })
}

io.on("connection", (socket) => {
    console.log("Web client connected");
    if (sock && sock.user) socket.emit("connected", "WhatsApp Connected Successfully!");

    socket.on("get-chats", async () => {
        if (sock) {
            const chats = await sock.groupFetchAllParticipating()
            socket.emit("chat-list", Object.values(chats))
        }
    })

    socket.on("select-chat", (chatId) => {
        selectedChat = chatId
        socket.emit("setup-complete", "Monitoring chat: " + chatId)
        console.log("👀 Monitoring chat:", chatId)
    })

    // ── Notification reply handlers ───────────────────────────────────────────

    // User typed a manual reply via the notification banner
    socket.on("user-reply", async ({ msgId, jid, text }) => {
        const pending = pendingReplies.get(msgId)
        if (pending) { clearTimeout(pending.timer); pendingReplies.delete(msgId) }
        if (!text?.trim() || !jid) return
        try {
            const sentMsg = await sock.sendMessage(jid, { text: text.trim() })
            if (sentMsg?.key?.id) {
                sentMessageIds.add(sentMsg.key.id)
                _saveSentIds(sentMessageIds)
            }
            socket.emit("reply-sent", { jid, text })
        } catch (e) { socket.emit("error-reply", String(e)) }
    })

    // User dismissed the notification — no reply at all
    socket.on("user-dismiss", ({ msgId }) => {
        const pending = pendingReplies.get(msgId)
        if (pending) { clearTimeout(pending.timer); pendingReplies.delete(msgId) }
    })

    // User clicked "Auto-reply 5 min" — AI takes over using tone analysis
    socket.on("enable-auto-reply", async ({ msgId, jid }) => {
        const pending = pendingReplies.get(msgId)
        if (pending) { clearTimeout(pending.timer); pendingReplies.delete(msgId) }

        const toneMessages = myRecentMessages.get(jid) || []
        const autoInfo = { until: Date.now() + AUTO_REPLY_MS, toneMessages: [...toneMessages] }
        autoReplyChats.set(jid, autoInfo)
        socket.emit("auto-reply-enabled", { jid, minutes: AUTO_REPLY_MS / 60000 })
        console.log(`🤖 Auto-reply enabled for ${jid} (${toneMessages.length} tone samples)`)

        // Also reply to the current pending message now
        if (pending?.text) {
            try {
                const prompt    = buildTonePrompt(pending.text, pending.name, autoInfo)
                const aiResponse = await aiQueue.add(() => getAIResponse(prompt))
                const sentMsg   = await sock.sendMessage(jid, { text: aiResponse })
                if (sentMsg?.key?.id) {
                    sentMessageIds.add(sentMsg.key.id)
                    _saveSentIds(sentMessageIds)
                }
                socket.emit("auto-reply-sent", { jid, reply: aiResponse, name: pending.name })
            } catch (e) { console.error("Auto-reply initial send failed:", e) }
        }
    })

    // User stopped auto-reply mode manually
    socket.on("disable-auto-reply", ({ jid }) => {
        autoReplyChats.delete(jid)
        socket.emit("auto-reply-disabled", { jid })
        console.log(`🤖 Auto-reply disabled for ${jid}`)
    })
})

startWhatsApp()

server.listen(3000, () => {
    console.log("Server running on http://localhost:3000")
})
