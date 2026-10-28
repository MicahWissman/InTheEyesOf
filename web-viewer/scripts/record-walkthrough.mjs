#!/usr/bin/env node
// Records a video fly-through of a recording's point cloud along its SLAM
// trajectory, using the app's dev-only ?flythrough=1 capability
// (see NarrativeViewer.tsx: TrajectoryFlyThrough).
//
// Requires `npm run dev` already running (default https://localhost:5173).
//
// Usage:
//   node scripts/record-walkthrough.mjs [--recording=carona_adine]
//     [--duration=60] [--out=./carona-walkthrough.webm]
//     [--width=1920] [--height=1080] [--baseUrl=https://localhost:5173]
//     [--headless]

import { chromium } from 'playwright';
import { mkdir, rename, rm } from 'node:fs/promises';
import path from 'node:path';

function parseArgs(argv) {
  const args = {
    recording: 'carona_adine',
    duration: 60,
    width: 1920,
    height: 1080,
    baseUrl: 'https://localhost:5173',
    out: null,
    headless: false,
  };
  for (const arg of argv) {
    if (arg === '--headless') { args.headless = true; continue; }
    const m = arg.match(/^--([^=]+)=(.*)$/);
    if (!m) continue;
    const [, key, value] = m;
    if (key === 'duration' || key === 'width' || key === 'height') args[key] = Number(value);
    else args[key] = value;
  }
  return args;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const outPath = path.resolve(args.out ?? `./${args.recording}-walkthrough.webm`);
  const videoDir = path.resolve('.tmp-flythrough-video');
  await mkdir(videoDir, { recursive: true });

  const browser = await chromium.launch({ headless: args.headless });
  const context = await browser.newContext({
    viewport: { width: args.width, height: args.height },
    ignoreHTTPSErrors: true, // vite-plugin-basic-ssl uses a self-signed cert
    recordVideo: { dir: videoDir, size: { width: args.width, height: args.height } },
  });

  // Skip the one-time intro/welcome overlays so they never appear on camera.
  await context.addInitScript(() => {
    localStorage.setItem('eyesof:heard_intro', 'true');
    localStorage.setItem('eyesof:introDismissed', '1');
  });

  const page = await context.newPage();
  const video = page.video();

  try {
    const url = `${args.baseUrl}/?recording=${encodeURIComponent(args.recording)}` +
      `&flythrough=1&flythroughDuration=${args.duration}`;
    console.log(`[record-walkthrough] loading ${url}`);
    await page.goto(url, { waitUntil: 'load' });

    console.log('[record-walkthrough] waiting for point cloud to load...');
    // waitForFunction(pageFunction, arg, options) — arg is data passed into the
    // predicate, options (incl. timeout) is the third parameter.
    await page.waitForFunction(() => window.__pointCloudLoaded === true, undefined, { timeout: 60000 });

    console.log(`[record-walkthrough] recording ${args.duration}s fly-through along the SLAM trajectory...`);
    await page.waitForFunction(() => window.__flythroughDone === true, undefined, {
      timeout: (args.duration + 30) * 1000,
    });
    await page.waitForTimeout(500); // small settle buffer past the final frame
  } finally {
    await context.close();
    await browser.close();
  }

  if (!video) throw new Error('Playwright did not produce a video for this page');
  const recordedPath = await video.path();
  await rename(recordedPath, outPath);
  await rm(videoDir, { recursive: true, force: true });

  console.log(`[record-walkthrough] saved: ${outPath}`);
}

main().catch(err => {
  console.error('[record-walkthrough] failed:', err);
  process.exitCode = 1;
});
