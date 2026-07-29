'use strict';
// Load .env from repo root (GEMINI_API_KEY lives there, never in the client bundle)
require('dotenv').config({ path: require('path').join(__dirname, '../.env') });

const express = require('express');
const { GoogleGenerativeAI } = require('@google/generative-ai');

const PORT  = parseInt(process.env.ASK_PORT || '8787', 10);
// ── Swap this one line to test a different model (e.g. 'gemini-2.5-flash-lite') ──
const MODEL = 'gemini-2.5-flash';

const SYSTEM_INSTRUCTION = [
  'You are a concise museum and heritage-site guide.',
  'A visitor is physically standing at a specific location; answer only about what they are looking at.',
  'Stay strictly grounded in the LOCATION CONTEXT provided — do not invent facts, dates, or names.',
  'Reply in 2–3 spoken sentences, plain prose, no markdown, no bullet points.',
  'OUTPUT FORMAT: output ONLY a raw JSON object — no preamble, no explanation, no markdown fences, nothing before or after the JSON.',
  'Exact schema: {"answer":"your 2-3 sentence reply here","grounding":"grounded|partial|general"}',
  '"grounded"=fully supported by LOCATION CONTEXT; "partial"=partly context, partly general knowledge; "general"=not in context.',
].join(' ');

// Strip markdown code fences, then find and return the first balanced {...} block.
// String-aware walk: honours escape sequences and " delimiters so braces inside
// JSON string values are not counted toward depth.
function extractJsonBlock(raw) {
  // Remove ```[json] ... ``` fences, keeping only the content inside them
  const stripped = raw.replace(/```(?:json)?\s*([\s\S]*?)\s*```/g, '$1').trim();
  // Discard any prose before the first {
  const start = stripped.indexOf('{');
  if (start === -1) return null;
  let depth = 0, inStr = false, esc = false;
  for (let i = start; i < stripped.length; i++) {
    const c = stripped[i];
    if (esc)                 { esc = false; continue; }
    if (c === '\\' && inStr) { esc = true;  continue; }
    if (c === '"')           { inStr = !inStr; continue; }
    if (inStr)               continue;
    if (c === '{')           depth++;
    else if (c === '}' && --depth === 0) return stripped.slice(start, i + 1);
  }
  return null;
}

let genAI = null;
function getModel() {
  if (!process.env.GEMINI_API_KEY) throw new Error('GEMINI_API_KEY not set');
  if (!genAI) genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);
  return genAI.getGenerativeModel({
    model: MODEL,
    systemInstruction: SYSTEM_INSTRUCTION,
    generationConfig: {
      maxOutputTokens: 2048,
      temperature: 0.3,
      responseMimeType: 'application/json',
      // SDK 0.24.x passes generationConfig as-is to the REST API, so extra fields
      // are forwarded. thinkingBudget:0 disables the reasoning pass so all output
      // tokens go to the answer — prevents the truncated-JSON bug.
      thinkingConfig: { thinkingBudget: 0 },
    },
  });
}

const app = express();
app.use(express.json({ limit: '16kb' }));

// ── Health ────────────────────────────────────────────────────────────────────
app.get('/ask/health', (_req, res) => res.json({ ok: true }));

// ── Ask ───────────────────────────────────────────────────────────────────────
app.post('/ask', async (req, res) => {
  const { anchorContext, question, sessionMemory } = req.body ?? {};

  if (typeof question !== 'string' || !question.trim()) {
    return res.status(400).json({ error: 'question is required' });
  }
  if (!process.env.GEMINI_API_KEY) {
    return res.status(500).json({ error: 'AI service not configured on this device' });
  }

  // Build a single flat prompt from the three inputs
  const parts = [];
  if (anchorContext) parts.push(`LOCATION CONTEXT:\n${anchorContext.trim()}`);
  if (sessionMemory) parts.push(`SESSION NOTES:\n${sessionMemory.trim()}`);
  parts.push(`VISITOR QUESTION: ${question.trim()}`);
  const prompt = parts.join('\n\n');

  try {
    const result = await getModel().generateContent(prompt);
    const rawText = result.response.text().trim();
    const finishReason = result.response.candidates?.[0]?.finishReason ?? 'unknown';
    if (finishReason !== 'STOP') {
      console.warn('[ask-proxy] finishReason:', finishReason, '— rawText:', JSON.stringify(rawText));
    }
    let answer, grounding;
    try {
      const block = extractJsonBlock(rawText);
      const parsed = block ? JSON.parse(block) : null;
      if (parsed && typeof parsed.answer === 'string' && parsed.answer.trim()) {
        let innerAnswer    = parsed.answer.trim();
        let innerGrounding = parsed.grounding;
        // Unwrap double-nesting: answer is itself a JSON/fenced string
        if (innerAnswer.startsWith('{') || innerAnswer.includes('`')) {
          try {
            const innerBlock  = extractJsonBlock(innerAnswer);
            const innerParsed = innerBlock ? JSON.parse(innerBlock) : null;
            if (innerParsed && typeof innerParsed.answer === 'string' && innerParsed.answer.trim()) {
              innerAnswer    = innerParsed.answer.trim();
              innerGrounding = innerParsed.grounding;
            }
          } catch { /* keep outer answer */ }
        }
        answer    = innerAnswer;
        grounding = ['grounded', 'partial', 'general'].includes(innerGrounding)
          ? innerGrounding : 'general';
      } else {
        console.error('[ask-proxy] extraction failed — rawText:', JSON.stringify(rawText));
        answer    = '(could not parse answer)';
        grounding = 'general';
      }
    } catch (e) {
      console.error('[ask-proxy] extraction threw:', e?.message, '— rawText:', JSON.stringify(rawText));
      answer    = '(could not parse answer)';
      grounding = 'general';
    }
    return res.json({ answer, grounding });
  } catch (err) {
    console.error('[ask-proxy] Gemini error:', err?.message ?? err);
    return res.status(502).json({ error: 'AI request failed — try again' });
  }
});

// ── Start ─────────────────────────────────────────────────────────────────────
app.listen(PORT, '127.0.0.1', () => {
  const keyStatus = process.env.GEMINI_API_KEY ? '✓ API key loaded' : '✗ GEMINI_API_KEY missing — set it in .env';
  console.log(`[ask-proxy] 127.0.0.1:${PORT}  model=${MODEL}  ${keyStatus}`);
});
