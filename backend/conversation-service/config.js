'use strict';

module.exports = {
  PORT: process.env.PORT || 3001,

  // Gemini model — change to latest stable release as needed
  GEMINI_MODEL: process.env.GEMINI_MODEL || 'gemini-2.0-flash',

  // Generation settings
  MAX_TOKENS_OUT: 200,
  TEMPERATURE: 0.3,

  // Safety caps
  DAILY_COST_CAP_USD: parseFloat(process.env.DAILY_COST_CAP_USD || '1.00'),

  // Rate limiting
  RATE_LIMIT_WINDOW_MS: 60 * 1000,  // 1 minute window
  RATE_LIMIT_MAX: 5,                  // requests per window per IP

  // Conversation limits (enforced by client too, validated here)
  MAX_EXCHANGES: 5,
  MAX_SESSION_SECONDS: 60,

  // Filesystem: where public recordings live (relative to project root)
  // Override with RECORDINGS_DIR env var on the Pi
  RECORDINGS_DIR: process.env.RECORDINGS_DIR ||
    require('path').resolve(__dirname, '../../web-viewer/public/recordings'),

  // Gemini token pricing (USD per 1M tokens) — update if pricing changes
  // Gemini 2.0 Flash as of 2025: https://ai.google.dev/pricing
  INPUT_PRICE_PER_1M: parseFloat(process.env.INPUT_PRICE_PER_1M || '0.075'),
  OUTPUT_PRICE_PER_1M: parseFloat(process.env.OUTPUT_PRICE_PER_1M || '0.30'),
};
