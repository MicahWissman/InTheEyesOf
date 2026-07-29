'use strict';
require('dotenv').config();

const express = require('express');
const cors = require('cors');
const path = require('path');
const fs = require('fs');
const rateLimit = require('express-rate-limit');

const config = require('./config');
const costTracker = require('./costTracker');
const { buildSystemPrompt } = require('./promptTemplate');

// ── Gemini client (lazy — only created if API key present) ────────────────────
let genAI = null;
function getGenAI() {
  if (genAI) return genAI;
  const { GoogleGenerativeAI } = require('@google/generative-ai');
  genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);
  return genAI;
}

// ── Express setup ─────────────────────────────────────────────────────────────
const app = express();
app.use(express.json({ limit: '16kb' }));
app.use(cors({ origin: true, credentials: false }));

// Per-IP rate limit: 5 requests / minute
const limiter = rateLimit({
  windowMs: config.RATE_LIMIT_WINDOW_MS,
  max: config.RATE_LIMIT_MAX,
  standardHeaders: true,
  legacyHeaders: false,
  message: { error: 'Too many requests. Please wait a moment before asking again.' },
});
app.use('/api/', limiter);

// ── Health check ──────────────────────────────────────────────────────────────
app.get('/api/health', (_req, res) => {
  const keyConfigured = !!process.env.GEMINI_API_KEY;
  const dailyCost = costTracker.getDailyCost();
  res.json({
    ok: true,
    aiConfigured: keyConfigured,
    dailyCostUSD: dailyCost.toFixed(4),
    capUSD: config.DAILY_COST_CAP_USD,
    overCap: costTracker.isOverCap(),
  });
});

// ── POST /api/conversation ────────────────────────────────────────────────────
app.post('/api/conversation', async (req, res) => {
  // 1. API key guard
  if (!process.env.GEMINI_API_KEY) {
    return res.status(500).json({ error: 'AI service not configured on this device.' });
  }

  // 2. Daily cost cap
  if (costTracker.isOverCap()) {
    return res.status(429).json({
      error: `Daily cost cap of $${config.DAILY_COST_CAP_USD} reached. AI is paused until tomorrow.`,
    });
  }

  // 3. Validate request shape
  const { anchorId, recordingId, message, conversationHistory, secondsRemaining } = req.body;
  if (
    typeof anchorId === 'undefined' ||
    typeof recordingId !== 'string' ||
    typeof message !== 'string' ||
    !message.trim() ||
    !Array.isArray(conversationHistory)
  ) {
    return res.status(400).json({ error: 'Invalid request shape.' });
  }

  // 4. Validate conversation limits (client enforces too, but verify server-side)
  if (conversationHistory.length >= config.MAX_EXCHANGES * 2) {
    return res.status(400).json({ error: 'Maximum exchanges reached.' });
  }
  if (typeof secondsRemaining === 'number' && secondsRemaining <= 0) {
    return res.status(400).json({ error: 'Session timed out.' });
  }

  // 5. Load corpus file
  const anchorIdStr = String(anchorId).padStart(3, '0');
  const corpusPath = path.join(
    config.RECORDINGS_DIR,
    recordingId,
    'corpus',
    `anchor_${anchorIdStr}.txt`,
  );

  if (!fs.existsSync(corpusPath)) {
    return res.status(404).json({
      error: `No corpus available for anchor ${anchorId} in recording '${recordingId}'. Corpus files are populated after the field recording session.`,
    });
  }

  let corpusContent;
  try {
    corpusContent = fs.readFileSync(corpusPath, 'utf8');
  } catch {
    return res.status(500).json({ error: 'Could not read corpus file.' });
  }

  // 6. Build prompt and call Gemini
  try {
    const ai = getGenAI();
    const model = ai.getGenerativeModel({
      model: config.GEMINI_MODEL,
      systemInstruction: buildSystemPrompt(
        { id: anchorId, narrative_title: `Anchor ${anchorId}` },
        corpusContent,
        recordingId,
      ),
      generationConfig: {
        maxOutputTokens: config.MAX_TOKENS_OUT,
        temperature: config.TEMPERATURE,
      },
    });

    // Build chat history from prior exchanges
    const history = conversationHistory
      .filter(h => h.role && h.text)
      .map(h => ({
        role: h.role === 'user' ? 'user' : 'model',
        parts: [{ text: String(h.text) }],
      }));

    const chat = model.startChat({ history });
    const result = await chat.sendMessage(message.trim());
    const responseText = result.response.text();
    const usage = result.response.usageMetadata || {};

    // 7. Track cost
    const inputTokens = usage.promptTokenCount || 0;
    const outputTokens = usage.candidatesTokenCount || 0;
    const callCost = costTracker.addCost(inputTokens, outputTokens);
    const dailyTotal = costTracker.getDailyCost();

    const exchangesUsed = Math.floor((conversationHistory.length + 2) / 2);
    const exchangesRemaining = Math.max(0, config.MAX_EXCHANGES - exchangesUsed);

    return res.json({
      response: responseText,
      exchangesRemaining,
      secondsRemaining: secondsRemaining ?? null,
      callCostUSD: callCost.toFixed(5),
      dailyCostUSD: dailyTotal.toFixed(4),
    });

  } catch (err) {
    console.error('[conversation-service] Gemini error:', err?.message || err);
    return res.status(502).json({ error: 'AI service request failed. Please try again.' });
  }
});

// ── Start ─────────────────────────────────────────────────────────────────────
app.listen(config.PORT, '127.0.0.1', () => {
  const keyStatus = process.env.GEMINI_API_KEY ? '✓ API key loaded' : '✗ GEMINI_API_KEY missing';
  console.log(`[conversation-service] Listening on 127.0.0.1:${config.PORT} — ${keyStatus}`);
  console.log(`[conversation-service] Model: ${config.GEMINI_MODEL}  Cap: $${config.DAILY_COST_CAP_USD}/day`);
});
