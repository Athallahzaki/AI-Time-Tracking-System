// Pengaturan tampilan video + overlay, dibaca dari /display-config.json saat start.
// File itu bisa di-mount ke container (deploy/docker-compose.yml) dan diubah tanpa
// build ulang: cukup refresh browser. Nilai yang hilang atau tidak valid memakai
// default di bawah (= perilaku sebelum file ini ada) dan memberi peringatan di konsol.

export interface DisplayConfig {
  webrtc: {
    /** Detik video WebRTC sengaja ditahan agar kotak dari engine sempat tiba. */
    playoutDelaySeconds: number;
  };
  hls: {
    lowLatencyMode: boolean;
    backBufferLength: number;
    /** Detik di belakang ujung live (hls.js `liveSyncDuration`). null = default hls.js. */
    liveSyncDurationSeconds: number | null;
  };
  boxes: {
    /** Kotak lebih tua dari ini (ms) dari waktu video disembunyikan. null = tanpa batas. */
    maxAgeMs: number | null;
    /** Riwayat kotak live yang disimpan untuk dicocokkan dengan video (ms). */
    bufferWindowMs: number;
    /** Toleransi selisih PTS kotak vs video di mode file/MP4 (detik). */
    maxDirectPtsDifferenceSeconds: number;
  };
  interpolation: {
    enabled: boolean;
    maxGapMs: number;
    lostHoldMs: number;
    /** Pergeseran pusat maksimum (persen lebar/tinggi frame) yang masih di-lerp. */
    maxJumpPercent: number;
  };
}

export const DEFAULT_DISPLAY_CONFIG: DisplayConfig = {
  webrtc: { playoutDelaySeconds: 8.5 },
  hls: { lowLatencyMode: true, backBufferLength: 4, liveSyncDurationSeconds: null },
  boxes: { maxAgeMs: null, bufferWindowMs: 8000, maxDirectPtsDifferenceSeconds: 1.0 },
  interpolation: { enabled: true, maxGapMs: 500, lostHoldMs: 300, maxJumpPercent: 25 },
};

// Batas wajar per angka: nilai di luar rentang ini hampir pasti salah ketik.
const RANGES: Record<string, [number, number]> = {
  'webrtc.playoutDelaySeconds': [0, 30],
  'hls.backBufferLength': [0, 600],
  'hls.liveSyncDurationSeconds': [0.5, 60],
  'boxes.maxAgeMs': [50, 60_000],
  'boxes.bufferWindowMs': [1000, 120_000],
  'boxes.maxDirectPtsDifferenceSeconds': [0.05, 10],
  'interpolation.maxGapMs': [0, 10_000],
  'interpolation.lostHoldMs': [0, 10_000],
  'interpolation.maxJumpPercent': [0, 100],
};

const NULLABLE = new Set(['hls.liveSyncDurationSeconds', 'boxes.maxAgeMs']);

/** Dipakai seluruh aplikasi. Diisi `loadDisplayConfig()` sebelum app di-mount. */
export const displayConfig: DisplayConfig = structuredClone(DEFAULT_DISPLAY_CONFIG);

/** Gabungkan `raw` ke default, field demi field. Kembalikan hasil + daftar peringatan. */
export function mergeDisplayConfig(raw: unknown): { config: DisplayConfig; warnings: string[] } {
  const config = structuredClone(DEFAULT_DISPLAY_CONFIG);
  const warnings: string[] = [];
  if (raw === undefined || raw === null) return { config, warnings };
  if (typeof raw !== 'object' || Array.isArray(raw)) {
    return { config, warnings: ['display-config.json bukan objek JSON; semua memakai default'] };
  }
  const target = config as unknown as Record<string, Record<string, unknown>>;
  for (const [section, values] of Object.entries(raw as Record<string, unknown>)) {
    if (section.startsWith('_')) continue; // "_komentar" dsb.
    const defaults = target[section];
    if (!defaults) {
      warnings.push(`bagian tidak dikenal: ${section}`);
      continue;
    }
    if (typeof values !== 'object' || values === null || Array.isArray(values)) {
      warnings.push(`${section} harus objek`);
      continue;
    }
    for (const [key, value] of Object.entries(values as Record<string, unknown>)) {
      if (key.startsWith('_')) continue;
      const path = `${section}.${key}`;
      if (!(key in defaults)) {
        warnings.push(`kunci tidak dikenal: ${path}`);
        continue;
      }
      const fallback = (DEFAULT_DISPLAY_CONFIG as unknown as Record<string, Record<string, unknown>>)[section][key];
      if (value === null && NULLABLE.has(path)) {
        defaults[key] = null;
      } else if (typeof fallback === 'boolean' || typeof value === 'boolean') {
        if (typeof value === 'boolean' && typeof fallback === 'boolean') defaults[key] = value;
        else warnings.push(`${path} harus true/false`);
      } else if (typeof value === 'number' && Number.isFinite(value)) {
        const [min, max] = RANGES[path] ?? [-Infinity, Infinity];
        if (value >= min && value <= max) defaults[key] = value;
        else warnings.push(`${path}=${value} di luar ${min}..${max}; memakai ${String(fallback)}`);
      } else {
        warnings.push(`${path} harus angka${NULLABLE.has(path) ? ' atau null' : ''}`);
      }
    }
  }
  return { config, warnings };
}

async function fetchJson(url: string): Promise<unknown> {
  try {
    const response = await fetch(url, { cache: 'no-store', credentials: 'same-origin' });
    if (response.ok) return await response.json();
    if (response.status !== 404) console.warn(`[display-config] ${url}: HTTP ${response.status}`);
  } catch (error) {
    // File tidak ada -> fallback SPA mengembalikan HTML -> JSON gagal: pakai default.
    console.warn(`[display-config] ${url} gagal dibaca; diabaikan`, error);
  }
  return undefined;
}

/** File di server (operator) sebagai dasar, lalu pengaturan admin dari dashboard di atasnya. */
export function layerDisplayConfig(...layers: unknown[]): Record<string, Record<string, unknown>> {
  const out: Record<string, Record<string, unknown>> = {};
  for (const layer of layers) {
    if (!layer || typeof layer !== 'object' || Array.isArray(layer)) continue;
    for (const [section, values] of Object.entries(layer as Record<string, unknown>)) {
      if (values && typeof values === 'object' && !Array.isArray(values)) {
        out[section] = { ...(out[section] ?? {}), ...(values as Record<string, unknown>) };
      } else {
        out[section] = values as Record<string, unknown>; // bentuk salah: biar mergeDisplayConfig memperingatkan
      }
    }
  }
  return out;
}

/** Terapkan ke objek yang dipakai aplikasi, per bagian (referensi seperti INTERP_CONFIG tetap sah). */
export function applyDisplayConfig(raw: unknown): string[] {
  const { config, warnings } = mergeDisplayConfig(raw);
  for (const section of Object.keys(config) as (keyof DisplayConfig)[]) {
    Object.assign(displayConfig[section], config[section]);
  }
  return warnings;
}

/** /display-config.json (file, di-mount) + /api/settings/display (admin). Gagal = default. */
export async function loadDisplayConfig(
  fileUrl = '/display-config.json',
  apiUrl: string | null = '/api/settings/display',
): Promise<void> {
  const [file, admin] = await Promise.all([fetchJson(fileUrl), apiUrl ? fetchJson(apiUrl) : undefined]);
  for (const warning of applyDisplayConfig(layerDisplayConfig(file, admin))) {
    console.warn(`[display-config] ${warning}`);
  }
}
