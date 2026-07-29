'use strict';
const fs = require('fs');
const path = require('path');
const config = require('./config');

const LOG_DIR = path.join(__dirname, 'data');
const LOG_FILE = path.join(LOG_DIR, 'cost_log.json');

function today() {
  return new Date().toISOString().slice(0, 10); // YYYY-MM-DD
}

function readLog() {
  if (!fs.existsSync(LOG_FILE)) return {};
  try { return JSON.parse(fs.readFileSync(LOG_FILE, 'utf8')); }
  catch { return {}; }
}

function writeLog(data) {
  if (!fs.existsSync(LOG_DIR)) fs.mkdirSync(LOG_DIR, { recursive: true });
  fs.writeFileSync(LOG_FILE, JSON.stringify(data, null, 2));
}

function getDailyCost() {
  return readLog()[today()] || 0;
}

function addCost(inputTokens, outputTokens) {
  const cost =
    (inputTokens / 1_000_000) * config.INPUT_PRICE_PER_1M +
    (outputTokens / 1_000_000) * config.OUTPUT_PRICE_PER_1M;

  const log = readLog();
  const key = today();
  log[key] = (log[key] || 0) + cost;
  writeLog(log);
  return cost;
}

function isOverCap() {
  return getDailyCost() >= config.DAILY_COST_CAP_USD;
}

module.exports = { getDailyCost, addCost, isOverCap };
