const express = require("express")
const { default: makeWASocket, useMultiFileAuthState, fetchLatestBaileysVersion } = require("@whiskeysockets/baileys")
const P = require("pino")
const QRCode = require("qrcode")
const http = require("http")
const { Server } = require("socket.io")
const axios = require("axios")

const app = express()
const server = http.createServer(app)
const io = new Server(server)

app.use(express.static(__dirname))

let sock
let selectedChat = null

// --- STATE MANAGEMENT ---
const USER_COOLDOWN_MS =  1000; // 1 sec Rate Limit
const userMessageTracker = new Map();
const sentMessageIds = new Set(); // Loop protection

// --- THE BRIDGE FUNCTION ---
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
            console.log("❌ Connection closed. Reason:", lastDisconnect?.error);
            startWhatsApp()
        }
    })

    // --- MONITOR MODE LOGIC ---
    sock.ev.on("messages.upsert", async ({ messages }) => {
        const msg = messages[0]

        if (!msg.message) return

            // 1. ECHO PROTECTION (Stop loops)
            // If we just sent this message ID, ignore it.
            if (sentMessageIds.has(msg.key.id)) {
                sentMessageIds.delete(msg.key.id)
                return
            }

            const text =
            msg.message.conversation ||
            msg.message.extendedTextMessage?.text

            if (!text) return

                const sender = msg.key.remoteJid

                // 2. SCOPE CHECK
                // If no chat selected, or message is from a different chat -> IGNORE
                if (!selectedChat || sender !== selectedChat) {
                    return
                }

                // At this point, the message is inside the SELECTED CHAT.
                // We proceed to reply logic.

                // 3. Identify Sender (for logging/rate limiting)
                const senderParticipant = msg.key.participant || sender

                // 4. Rate Limiting (Prevent spam flood)
                const now = Date.now()
                const lastReplyTime = userMessageTracker.get(senderParticipant)

                if (lastReplyTime && now - lastReplyTime < USER_COOLDOWN_MS) {
                    console.log(`⛔ Rate limited: ${senderParticipant}`)
                    return
                }

                // 5. REPLY
                console.log("\n--- 🚨 UPSERT FIRED (MONITOR MODE) 🚨 ---");
                console.log("📩 Received:", text);

                const aiResponse = await getAIResponse(text)

                try {
                    // Send and Capture ID
                    const sentMsg = await sock.sendMessage(sender, { text: aiResponse })
                    console.log("✅ Replied to:", sender);

                    // Add ID to protection set to prevent infinite loop
                    if (sentMsg && sentMsg.key && sentMsg.key.id) {
                        sentMessageIds.add(sentMsg.key.id)
                    }

                    // Update Rate Limit
                    userMessageTracker.set(senderParticipant, now)

                } catch (e) {
                    console.error("Failed to send:", e)
                }
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
})

startWhatsApp()

server.listen(3000, () => {
    console.log("Server running on http://localhost:3000")
})
