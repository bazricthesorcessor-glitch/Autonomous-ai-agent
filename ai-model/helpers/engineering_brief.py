# AVRIL ENGINEERING BRIEF
# Owner: Divyansh (Bazric)
# Date: 2026-03-12
# Purpose: Reference document for system architecture, known bugs, and roadmap
# ═══════════════════════════════════════════════════════════════════════════════

# PROJECT GOAL
# Avril is a local autonomous AI assistant that can:
# - Chat with the user via local LLM
# - See the screen (OCR + DOM control via Playwright)
# - Execute tasks on the computer
# - Remember information (facts, tasks, goals, daily logs)
# - Manage multi-step tasks with retry + loop detection
# - Control the OS (Hyprland window manager, ydotool)
# - Be controlled remotely via WhatsApp
# - Provide a full UI control panel at localhost:8000/app

# ═══════════════════════════════════════════════════════════════════════════════
# ARCHITECTURE (3 Layers)
# ═══════════════════════════════════════════════════════════════════════════════
#
#   Browser UI (localhost:8000/app)
#        ↓ HTTP (fetch)
#   Python AI Backend (Flask :8000)
#        ↓
#   Agent Loop + Tools
#
#   Remote:
#   WhatsApp → Node.js Baileys Bridge (:3000) → POST /chat → Python Backend
#
# ═══════════════════════════════════════════════════════════════════════════════
# TOOL LAYERS (Priority Order)
# ═══════════════════════════════════════════════════════════════════════════════
#
#   Layer 1: browser_control (Playwright)  — websites, DOM-based, most reliable
#   Layer 2: computer_use (OCR + ydotool)  — desktop apps, screen element map
#   Layer 3: window_manager (hyprctl)      — OS window control
#   Layer 4: terminal_safe                 — allowlisted shell commands
#
# ═══════════════════════════════════════════════════════════════════════════════
# KNOWN BUGS (to fix)
# ═══════════════════════════════════════════════════════════════════════════════
#
# 1. chat.js — duplicate user messages rendered sometimes
# 2. Markdown italic regex uses negative lookbehind — breaks some browsers
# 3. localStorage overflow — chat history stores full responses, no length cap
# 4. Settings panel rebuilds DOM + handlers each open (memory leak)
# 5. Screen watch — multiple polling intervals can stack
# 6. WhatsApp group msgs — remoteJid vs participant mix-up
# 7. WhatsApp reconnect — connection close can create multiple sockets
# 8. No message length limit — huge messages can overload the AI
#
# ═══════════════════════════════════════════════════════════════════════════════
# SECURITY RISKS
# ═══════════════════════════════════════════════════════════════════════════════
#
# 1. Prompt injection from group chats
# 2. WhatsApp account compromise = OS control
# 3. Tool risk classification needed: safe | interactive | dangerous
#
# ═══════════════════════════════════════════════════════════════════════════════
# ROADMAP
# ═══════════════════════════════════════════════════════════════════════════════
#
# Performance:
#   - Streaming token responses
#   - Message batching for rapid inputs
#
# New capabilities:
#   - Voice interface (mic → STT → AI → TTS)
#   - File uploads (drag-and-drop images, PDFs, docs)
#   - Multi-chat sessions in UI
#   - Internal event bus (tool_run, task_created, ai_response)
#
# Visual task execution (partially implemented):
#   - Playwright for websites (DONE)
#   - Accessibility tree for desktop apps (pyatspi — planned)
#   - OmniParser/YOLO for vision fallback (planned)
#
# ═══════════════════════════════════════════════════════════════════════════════
# DESIGN PRINCIPLES
# ═══════════════════════════════════════════════════════════════════════════════
#
# 1. Local first — all intelligence runs locally
# 2. Transparency — user sees what AI is doing
# 3. Safety — dangerous ops require confirmation
# 4. Modularity — UI, agent, tools, messaging stay separate
