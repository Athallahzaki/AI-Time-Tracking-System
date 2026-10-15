/**
 * Interpolasi posisi kotak antar frame analisis (dok. 12 §3.7).
 *
 * Engine menganalisis ±6 fps, layar menggambar ±60 fps. Tanpa interpolasi kotak
 * melompat tiap ~167 ms. Di sini posisi kotak di waktu t dihitung dari dua frame
 * analisis pengapit A (≤ t) dan B (> t), dipasangkan per track:
 *
 *   - track ada di A dan B      → posisi di-lerp dengan α = (t − tA) / (tB − tA)
 *   - track baru (hanya di B)   → tidak diinterpolasi; muncul saat t lebih dekat ke B
 *   - track hilang (hanya di A) → ditahan di posisi terakhir maksimal 0,3 detik
 *   - jarak A–B > 0,5 detik     → tidak diinterpolasi (frame terdekat), supaya kotak
 *                                 tidak "meluncur" palsu melintasi stall/frame hilang
 *   - lompatan besar (> 25% lebar frame) → snap, kemungkinan ID switch
 *
 * Hanya geometri yang diinterpolasi. Label/status/timer diambil dari frame yang
 * lebih baru (B) untuk track yang cocok.
 *
 * Konsekuensi: butuh frame SESUDAH t. HLS (tertinggal beberapa detik) dan WebRTC
 * (playout delay 0,8 dtk di CameraFeedCard) sudah memenuhi itu.
 *
 * Matikan untuk perbandingan: tambahkan ?interp=0 di URL dashboard.
 */

export interface BoxGeom {
  /** Semua dalam persen terhadap frame (0–100). */
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface InterpolatableBox {
  /** Kunci track stabil (track_uuid). Tanpa kunci → tidak diinterpolasi. */
  interpKey?: string;
  geom?: BoxGeom;
  top: string;
  left: string;
  width: string;
  height: string;
}

export const INTERP_CONFIG = {
  maxGapMs: 500,
  lostHoldMs: 300,
  /** Pergeseran pusat maksimum (persen lebar/tinggi frame) yang masih di-lerp. */
  maxJumpPercent: 25,
};

let enabledCache: boolean | null = null;
export function interpolationEnabled(): boolean {
  if (enabledCache === null) {
    try {
      enabledCache = new URLSearchParams(window.location.search).get('interp') !== '0';
    } catch {
      enabledCache = true;
    }
  }
  return enabledCache;
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

export function withGeom<T extends InterpolatableBox>(item: T, g: BoxGeom): T {
  return {
    ...item,
    geom: g,
    left: `${g.x.toFixed(2)}%`,
    top: `${g.y.toFixed(2)}%`,
    width: `${g.w.toFixed(2)}%`,
    height: `${g.h.toFixed(2)}%`,
  };
}

function bigJump(a: BoxGeom, b: BoxGeom): boolean {
  const dx = Math.abs(a.x + a.w / 2 - (b.x + b.w / 2));
  const dy = Math.abs(a.y + a.h / 2 - (b.y + b.h / 2));
  return dx > INTERP_CONFIG.maxJumpPercent || dy > INTERP_CONFIG.maxJumpPercent;
}

/**
 * @param a   kotak di frame A (waktu tA)
 * @param b   kotak di frame B (waktu tB > tA)
 * @param t   waktu tampilan (satuan sama dengan tA/tB, milidetik)
 */
export function interpolateBoxes<T extends InterpolatableBox>(
  a: T[],
  b: T[],
  tA: number,
  tB: number,
  t: number,
): T[] {
  const gap = tB - tA;
  const closerToB = t - tA >= tB - t;
  if (!(gap > 0) || gap > INTERP_CONFIG.maxGapMs) {
    return closerToB ? b : a;
  }
  const alpha = Math.min(1, Math.max(0, (t - tA) / gap));

  const fromA = new Map<string, T>();
  for (const item of a) if (item.interpKey) fromA.set(item.interpKey, item);
  const seen = new Set<string>();
  const out: T[] = [];

  for (const item of b) {
    const key = item.interpKey;
    if (!key) {
      if (closerToB) out.push(item);
      continue;
    }
    seen.add(key);
    const prev = fromA.get(key);
    if (!prev) {
      // Track baru: tidak diinterpolasi.
      if (closerToB) out.push(item);
      continue;
    }
    if (!prev.geom || !item.geom || bigJump(prev.geom, item.geom)) {
      out.push(closerToB || !prev.geom ? item : withGeom(item, prev.geom));
      continue;
    }
    out.push(
      withGeom(item, {
        x: lerp(prev.geom.x, item.geom.x, alpha),
        y: lerp(prev.geom.y, item.geom.y, alpha),
        w: lerp(prev.geom.w, item.geom.w, alpha),
        h: lerp(prev.geom.h, item.geom.h, alpha),
      }),
    );
  }

  for (const item of a) {
    const key = item.interpKey;
    if (!key) {
      if (!closerToB) out.push(item);
      continue;
    }
    if (seen.has(key)) continue;
    // Track hilang: tahan sebentar di posisi terakhir.
    if (t - tA <= INTERP_CONFIG.lostHoldMs) out.push(item);
  }

  return out;
}

/**
 * Cari dua frame pengapit di buffer yang terurut naik berdasarkan `timeOf`
 * lalu interpolasi. Mengembalikan null bila buffer kosong.
 */
export function resolveInterpolated<F, T extends InterpolatableBox>(
  buffer: F[],
  timeOf: (frame: F) => number,
  boxesOf: (frame: F) => T[],
  t: number,
): { boxes: T[]; nearestDistance: number } | null {
  if (!buffer.length) return null;
  // Pencarian biner: indeks pertama dengan waktu > t.
  let low = 0;
  let high = buffer.length;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (timeOf(buffer[mid]) <= t) low = mid + 1;
    else high = mid;
  }
  const after = low < buffer.length ? buffer[low] : null;
  const before = low > 0 ? buffer[low - 1] : null;

  if (before && after) {
    const tA = timeOf(before);
    const tB = timeOf(after);
    return {
      boxes: interpolateBoxes(boxesOf(before), boxesOf(after), tA, tB, t),
      nearestDistance: Math.min(Math.abs(t - tA), Math.abs(tB - t)),
    };
  }
  const only = (before ?? after) as F;
  return { boxes: boxesOf(only), nearestDistance: Math.abs(timeOf(only) - t) };
}
