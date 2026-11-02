// Cek display-config: `npm run check:display` (Node 22.6+). Tanpa test runner di frontend.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { mergeDisplayConfig, DEFAULT_DISPLAY_CONFIG, displayConfig, loadDisplayConfig } from '../src/config/display.ts';

// File di repo = persis default, tanpa peringatan.
const file = JSON.parse(readFileSync(new URL('../public/display-config.json', import.meta.url), 'utf8'));
let r = mergeDisplayConfig(file);
assert.deepEqual(r.config, DEFAULT_DISPLAY_CONFIG); assert.deepEqual(r.warnings, []);

// Nilai valid diterapkan, salah ketik ditolak per field.
r = mergeDisplayConfig({ webrtc: { playoutDelaySeconds: 5 }, hls: { liveSyncDurationSeconds: 3, lowLatencyMode: 'ya' },
  boxes: { maxAgeMs: 99999, bufferWindowMs: 10000 }, interpolation: { enabeld: false }, video: {} });
assert.equal(r.config.webrtc.playoutDelaySeconds, 5);
assert.equal(r.config.hls.liveSyncDurationSeconds, 3);
assert.equal(r.config.hls.lowLatencyMode, true);
assert.equal(r.config.boxes.maxAgeMs, null);
assert.equal(r.config.boxes.bufferWindowMs, 10000);
assert.equal(r.warnings.length, 4, r.warnings.join(' | '));
assert.ok(r.warnings.some((w) => w.includes('interpolation.enabeld')));
assert.equal(mergeDisplayConfig([1]).warnings.length, 1);
assert.equal(mergeDisplayConfig({ boxes: { maxAgeMs: '1000' } }).config.boxes.maxAgeMs, null);

// loadDisplayConfig: referensi bagian tetap sama (INTERP_CONFIG), HTML fallback SPA tidak merusak.
const interp = displayConfig.interpolation;
globalThis.fetch = async () => new Response(JSON.stringify({ interpolation: { maxGapMs: 900 } }));
await loadDisplayConfig();
assert.equal(interp.maxGapMs, 900); assert.equal(displayConfig.interpolation, interp);
const warn = console.warn; console.warn = () => {};
globalThis.fetch = async () => new Response('<!doctype html>', { status: 200 });
await loadDisplayConfig();
console.warn = warn;
assert.equal(interp.maxGapMs, 500, 'file rusak kembali ke default');
console.log('display-config: semua cek lulus');
