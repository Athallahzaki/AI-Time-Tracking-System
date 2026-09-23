<script setup>
import { ref, reactive, watch, onMounted, onBeforeUnmount, computed } from 'vue';
import Hls from 'hls.js';
import { Circle, ScanSearch, TriangleAlert, Video, Wifi } from '@lucide/vue';
import DetectionBox from './DetectionBox.vue';
import {
  resolveDetectionsAt,
  resolveDetectionsAtPts,
  serverNowSeconds,
} from '@/composables/useDetectionStream.ts';

const props = defineProps({
  camera: { type: Object, required: true },
  compact: { type: Boolean, default: false },
});

const videoEl = ref(null);
const streamError = ref(false);
const streamMode = ref(''); // 'webrtc' | 'hls' | 'direct' | ''
const directSyncWaiting = ref(false);

let pc = null; // RTCPeerConnection for WebRTC
let hls = null; // Hls instance for HLS
let directLagStartedAtMs = null;

const maxDwellTime = computed(() => {
  if (!displayDetections.value || displayDetections.value.length === 0)
    return 'Inactive';
  const extras = displayDetections.value.map((d) => d.extra).filter(Boolean);
  return extras.length > 0 ? extras[0] : 'Active';
});

const videoContentRect = reactive({ left: 0, top: 0, width: 100, height: 100 });

function updateVideoContentRect() {
  const video = videoEl.value;
  if (!video || !video.videoWidth || !video.videoHeight) return;

  const containerW = video.clientWidth;
  const containerH = video.clientHeight;
  if (!containerW || !containerH) return;

  const videoAspect = video.videoWidth / video.videoHeight;
  const containerAspect = containerW / containerH;

  let renderedW;
  let renderedH;
  if (videoAspect > containerAspect) {
    // Video lebih "lebar" dari container → tinggi penuh, lebar overflow (crop kiri/kanan)
    renderedH = containerH;
    renderedW = containerH * videoAspect;
  } else {
    // Video lebih "tinggi" dari container → lebar penuh, tinggi overflow (crop atas/bawah)
    renderedW = containerW;
    renderedH = containerW / videoAspect;
  }

  const offsetX = (containerW - renderedW) / 2;
  const offsetY = (containerH - renderedH) / 2;

  videoContentRect.left = (offsetX / containerW) * 100;
  videoContentRect.top = (offsetY / containerH) * 100;
  videoContentRect.width = (renderedW / containerW) * 100;
  videoContentRect.height = (renderedH / containerH) * 100;
}

let resizeObserver = null;
const displayDetections = ref([]);
let rafId = null;

function formatLiveDuration(seconds) {
  const whole = Math.max(0, Math.floor(seconds));
  if (whole < 60) return `${whole}s`;
  const minutes = Math.floor(whole / 60);
  const remaining = whole % 60;
  if (minutes < 60) return `${minutes}m ${remaining}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m ${remaining}s`;
}

// Timers read the GLOBAL clock (backend wall clock, see serverNowSeconds in
// useDetectionStream). Each box carries absolute timestamps: first_seen_at and
// timer_as_of. Whatever frame is on screen -- live, delayed HLS, or a direct
// MP4 at 0.8x -- "how long" is server_now - first_seen_at, so one second on
// screen is exactly one second and switching frames cannot speed it up.
const lastShown = new Map();   // per-track guard against tiny clock-offset steps back
const LAST_SHOWN_TTL_MS = 30000;

function monotonic(key, value, nowMs) {
  const previous = lastShown.get(key);
  const shown = previous && value < previous.value && previous.value - value < 1
    ? previous.value
    : value;
  lastShown.set(key, { value: shown, seenMs: nowMs });
  return shown;
}

function pruneShown(nowMs) {
  for (const [key, entry] of lastShown) {
    if (nowMs - entry.seenMs > LAST_SHOWN_TTL_MS) lastShown.delete(key);
  }
}

function withLiveTimers(detections) {
  const nowMs = Date.now();
  const serverNow = serverNowSeconds();
  pruneShown(nowMs);
  return (detections || []).map((detection) => {
    const key = detection.track_id ?? detection.id;
    let elapsed;
    let sinceAsOf;
    if (detection.firstSeenAt != null && detection.timerAsOf != null) {
      elapsed = Math.max(0, serverNow - detection.firstSeenAt);
      sinceAsOf = Math.max(0, serverNow - detection.timerAsOf);
    } else if (detection.elapsedSeconds != null && detection.elapsedObservedAtMs != null) {
      // Older backend without absolute timestamps.
      sinceAsOf = Math.max(0, nowMs - detection.elapsedObservedAtMs) / 1000;
      elapsed = detection.elapsedSeconds + sinceAsOf;
    } else {
      return detection;
    }
    elapsed = monotonic(`${key}:e`, elapsed, nowMs);

    let extra = `${formatLiveDuration(elapsed)}${detection.durationSuffix || ''}`;
    if (detection.timerMode === 'qualifying') {
      const remaining = Math.max(0, (detection.qualificationRemainingSeconds || 0) - sinceAsOf);
      extra = `Validasi orang lewat ${Math.ceil(remaining)}s`;
    } else if (detection.timerMode === 'paused') {
      extra = 'Istirahat 12:00–13:00 · timer dijeda';
    } else if (detection.timerMode === 'counting' || detection.timerMode === 'limit') {
      const used = monotonic(`${key}:u`, (detection.dailyUsedSeconds || 0) + sinceAsOf, nowMs);
      const allowance = detection.allowanceSeconds || 1800;
      extra = detection.timerMode === 'limit'
        ? `BATAS TERCAPAI · ${formatLiveDuration(used)} / ${formatLiveDuration(allowance)}`
        : `Jatah terpakai ${formatLiveDuration(used)} / ${formatLiveDuration(allowance)}`;
    }
    return {
      ...detection,
      extra,
    };
  });
}

function getHlsCurrentPDT() {
  if (streamMode.value !== 'hls' || !hls || !videoEl.value) return null;

  const level = hls.levels && hls.levels[hls.currentLevel];
  const details = level && level.details;
  if (!details || !details.fragments || !details.fragments.length) return null;

  const currentTime = videoEl.value.currentTime;
  let frag = details.fragments.find(
    (f) => currentTime >= f.start && currentTime < f.start + f.duration,
  );
  if (!frag) frag = details.fragments[details.fragments.length - 1];
  if (!frag || !frag.programDateTime) return null;

  return frag.programDateTime + (currentTime - frag.start) * 1000;
}

function computeTargetMs() {
  if (streamMode.value === 'hls') {
    const pdt = getHlsCurrentPDT();
    if (pdt) return pdt;
    // Fallback kalau metadata PDT belum tersedia (mis. baru mulai load)
  }
  if (streamMode.value === 'webrtc') {
    // Playout delay sengaja ditambahkan di receiver (lihat WEBRTC_PLAYOUT_DELAY),
    // jadi frame yang sedang tampil sedikit di belakang "sekarang".
    return Date.now() - WEBRTC_PLAYOUT_DELAY * 1000;
  }
  return Date.now();
}

function tick() {
  synchronizeDirectPlayback();
  const resolved =
    streamMode.value === 'direct'
      ? resolveDetectionsAtPts(props.camera, videoEl.value?.currentTime ?? 0)
      : resolveDetectionsAt(props.camera, computeTargetMs());
  displayDetections.value = withLiveTimers(resolved);
  rafId = requestAnimationFrame(tick);
}


function isWhepUrl(url) {
  return url && (url.endsWith('/whep') || url.includes('/whep?'));
}

function isHlsUrl(url) {
  return url && url.includes('.m3u8');
}

const WEBRTC_PLAYOUT_DELAY = 0.8;
// Direct-mode sync (seamless). The engine analyses the file at its own speed;
// if that is below real time the old code paused the video, waited for a
// 2 s lead, played again, caught up, paused again ... a visible stutter every
// few seconds. Now the video's playbackRate follows the engine's measured
// throughput so it slows down smoothly instead. Pausing stays only as a last
// resort when the engine stalls completely.
const DIRECT_TARGET_LEAD_SECONDS = 1.5;   // how far analysis should run ahead
const DIRECT_HARD_LAG_SECONDS = 1.0;      // video ahead of analysis by this -> pause
const DIRECT_SEEK_LAG_SECONDS = 3.0;      // further ahead than this -> jump back instead
const DIRECT_LAG_GRACE_MS = 1500;
const DIRECT_MIN_RATE = 0.25;
const DIRECT_RATE_GAIN = 0.4;             // per second of lead error
const DIRECT_RATE_STEP = 0.03;            // ignore tiny changes (no thrash)
const directRate = { lastPts: Number.NaN, lastMs: 0, engineRate: 1, prevLatest: Number.NaN };

function seekVideoTo(video, seconds) {
  const target = Math.max(0, seconds);
  if (Math.abs(video.currentTime - target) > 0.05) video.currentTime = target;
}

function measureEngineRate(latest) {
  const nowMs = performance.now();
  if (Number.isFinite(directRate.lastPts) && latest > directRate.lastPts) {
    const dt = (nowMs - directRate.lastMs) / 1000;
    if (dt >= 0.25) {
      const sample = (latest - directRate.lastPts) / dt;
      directRate.engineRate = 0.8 * directRate.engineRate + 0.2 * sample;
      directRate.lastPts = latest;
      directRate.lastMs = nowMs;
    }
  } else if (!Number.isFinite(directRate.lastPts) || latest < directRate.lastPts) {
    directRate.lastPts = latest;
    directRate.lastMs = nowMs;
  }
}

function setPlaybackRate(video, rate) {
  const clamped = Math.min(1, Math.max(DIRECT_MIN_RATE, rate));
  if (Math.abs(video.playbackRate - clamped) >= DIRECT_RATE_STEP || clamped === 1) {
    if (video.playbackRate !== clamped) video.playbackRate = clamped;
  }
}

function synchronizeDirectPlayback() {
  const video = videoEl.value;
  const buffer = props.camera.ptsFrameBuffer || [];
  if (!video || streamMode.value !== 'direct') return;

  const latest = buffer.length ? buffer[buffer.length - 1].pts : Number.NaN;
  const duration = Number.isFinite(video.duration) ? video.duration : Number.NaN;
  const analysisComplete = Number.isFinite(latest)
    && Number.isFinite(duration)
    && latest >= duration - 0.5;

  // With no analyzed frame at all, hold the first video frame immediately so
  // the beginning cannot be lost while the model warms up.
  if (!Number.isFinite(latest)) {
    if (!video.paused) video.pause();
    directSyncWaiting.value = true;
    return;
  }

  if (analysisComplete) {
    directLagStartedAtMs = null;
    setPlaybackRate(video, 1);
    if (directSyncWaiting.value) {
      directSyncWaiting.value = false;
      video.play().catch((error) => {
        console.debug('[Direct sync] Playback resume deferred:', error);
      });
    }
    return;
  }

  // The engine restarted the file (--loop-files, or a camera re-open): its
  // timeline went back to 0. Follow it instead of waiting a whole lap with
  // the video frozen near the end -- that was the "stuck at AI sync".
  const restarted = Number.isFinite(directRate.prevLatest)
    && latest < directRate.prevLatest - 1;
  directRate.prevLatest = latest;
  if (restarted) {
    directRate.lastPts = Number.NaN;
    seekVideoTo(video, latest - DIRECT_TARGET_LEAD_SECONDS);
  }

  measureEngineRate(latest);
  let lead = latest - video.currentTime;

  // Video far ahead of analysis (e.g. it looped on its own, or the engine was
  // restarted): jump back to where the engine is rather than freezing.
  if (lead < -DIRECT_SEEK_LAG_SECONDS) {
    seekVideoTo(video, latest - 0.2);
    lead = latest - video.currentTime;
  }

  // Last resort: the engine has stalled and the video overtook it.
  if (lead < -DIRECT_HARD_LAG_SECONDS) {
    if (directLagStartedAtMs == null) directLagStartedAtMs = performance.now();
    if (performance.now() - directLagStartedAtMs >= DIRECT_LAG_GRACE_MS) {
      if (!video.paused) video.pause();
      directSyncWaiting.value = true;
    }
    return;
  }
  directLagStartedAtMs = null;

  // Follow the engine: its throughput, corrected toward the target lead.
  const rate = directRate.engineRate
    + DIRECT_RATE_GAIN * (lead - DIRECT_TARGET_LEAD_SECONDS);
  setPlaybackRate(video, rate);

  if (directSyncWaiting.value && lead >= DIRECT_TARGET_LEAD_SECONDS) {
    directSyncWaiting.value = false;
    video.play().catch((error) => {
      console.debug('[Direct sync] Playback resume deferred:', error);
    });
  }
}

async function startWhep(url) {
  teardown();
  streamError.value = false;
  streamMode.value = 'webrtc';

  try {
    pc = new RTCPeerConnection({
      iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
    });
    const videoTransceiver = pc.addTransceiver('video', {
      direction: 'recvonly',
    });

    const audioTransceiver = pc.addTransceiver('audio', {
      direction: 'recvonly',
    });
    try {
      if ('playoutDelayHint' in videoTransceiver.receiver) {
        videoTransceiver.receiver.playoutDelayHint = WEBRTC_PLAYOUT_DELAY;
      }

      if ('playoutDelayHint' in audioTransceiver.receiver) {
        audioTransceiver.receiver.playoutDelayHint = WEBRTC_PLAYOUT_DELAY;
      }
    } catch (err) {
      console.warn('[WebRTC] Could not set playout delay hint:', err);
    }

    // Attach incoming tracks to the video element.
    pc.ontrack = (event) => {
      if (event.streams && event.streams[0] && videoEl.value) {
        videoEl.value.srcObject = event.streams[0];

        videoEl.value.play().catch((err) => {
          console.warn('[WebRTC] Autoplay failed:', err);
        });
      }
    };

    pc.onconnectionstatechange = () => {
      if (
        pc &&
        (pc.connectionState === 'failed' || pc.connectionState === 'closed')
      ) {
        streamError.value = true;
      }
    };

    // WHEP signaling: POST SDP offer, receive SDP answer
    const offer = await pc.createOffer();

    await pc.setLocalDescription(offer);

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/sdp',
      },
      body: offer.sdp,
    });

    if (!response.ok) {
      throw new Error(`WHEP signaling failed: HTTP ${response.status}`);
    }

    const answerSdp = await response.text();

    await pc.setRemoteDescription({
      type: 'answer',
      sdp: answerSdp,
    });
  } catch (err) {
    console.error('[WebRTC] WHEP error:', err);
    streamError.value = true;
    teardownWebRtc();
  }
}

// ─── HLS ─────────────────────────────────────────────────────────────────────

function startHls(url) {
  teardown();
  streamError.value = false;
  streamMode.value = 'hls';

  if (!videoEl.value) return;

  if (Hls.isSupported()) {
    hls = new Hls({ lowLatencyMode: true, backBufferLength: 4 });
    hls.loadSource(url);
    hls.attachMedia(videoEl.value);
    hls.on(Hls.Events.ERROR, (_event, data) => {
      if (data.fatal) {
        streamError.value = true;
        teardownHls();
      }
    });
  } else if (videoEl.value.canPlayType('application/vnd.apple.mpegurl')) {
    // Safari native HLS
    videoEl.value.src = url;
  } else {
    streamError.value = true;
  }
}

// ─── Direct src ───────────────────────────────────────────────────────────────

function startDirect(url) {
  teardown();
  streamError.value = false;
  streamMode.value = 'direct';
  directSyncWaiting.value = true;
  directLagStartedAtMs = null;
  directRate.lastPts = Number.NaN;
  directRate.prevLatest = Number.NaN;
  directRate.engineRate = 1;
  if (videoEl.value) {
    videoEl.value.src = url;
    videoEl.value.load();
  }
}

// ─── Teardown helpers ─────────────────────────────────────────────────────────

function teardownWebRtc() {
  if (pc) {
    pc.close();
    pc = null;
  }
  if (videoEl.value) videoEl.value.srcObject = null;
}

function teardownHls() {
  if (hls) {
    hls.destroy();
    hls = null;
  }
}

function teardown() {
  teardownWebRtc();
  teardownHls();
}

// ─── Route to correct player ──────────────────────────────────────────────────

function attachStream(url) {
  if (!url) {
    teardown();
    streamMode.value = '';
    return;
  }
  if (isWhepUrl(url)) startWhep(url);
  else if (isHlsUrl(url)) startHls(url);
  else startDirect(url);
}

watch(
  () => props.camera.stream_url,
  (newUrl) => attachStream(newUrl),
);

onMounted(() => {
  if (props.camera.stream_url) attachStream(props.camera.stream_url);

  if (videoEl.value) {
    videoEl.value.addEventListener('loadedmetadata', updateVideoContentRect);
    videoEl.value.addEventListener('resize', updateVideoContentRect);
    resizeObserver = new ResizeObserver(() => updateVideoContentRect());
    resizeObserver.observe(videoEl.value);
  }

  rafId = requestAnimationFrame(tick);
});

onBeforeUnmount(() => {
  teardown();
  if (videoEl.value) {
    videoEl.value.removeEventListener('loadedmetadata', updateVideoContentRect);
    videoEl.value.removeEventListener('resize', updateVideoContentRect);
  }
  if (resizeObserver) {
    resizeObserver.disconnect();
    resizeObserver = null;
  }
  if (rafId) {
    cancelAnimationFrame(rafId);
    rafId = null;
  }
});

function onVideoError() {
  if (streamMode.value !== 'webrtc') streamError.value = true;
}

function handleInspect() {
  window.open('/api/attendance/active', '_blank');
}

function handleWarning() {
  alert(
    `Manual warning signal dispatched for ${props.camera.name} (${props.camera.code})`,
  );
}
</script>

<template>
  <div
    class="overflow-hidden rounded-xl border bg-white shadow-xs transition-all"
  >
    <div
      class="flex flex-wrap items-center justify-between gap-1.5 sm:gap-2 border-b px-3 py-2 sm:px-4 sm:py-2.5"
    >
      <div
        class="flex items-center gap-2 text-xs sm:text-sm font-medium text-slate-800"
      >
        <span
          class="h-2 w-2 rounded-full shrink-0"
          :class="
            camera.is_running !== false
              ? 'bg-emerald-500 animate-pulse'
              : 'bg-slate-400'
          "
        ></span>
        <span class="truncate">{{ camera.code }}: {{ camera.name }}</span>
      </div>
      <div
        v-if="!compact"
        class="flex items-center gap-1.5 sm:gap-2.5 text-[11px] sm:text-xs text-slate-500"
      >
        <span class="font-medium text-slate-700">{{ camera.fps }} FPS</span>
        <span
          v-if="streamMode"
          class="rounded px-1.5 py-0.5 text-[10px] sm:text-[11px] font-medium bg-sky-50 text-sky-700 border border-sky-200"
          :title="camera.stream_url"
        >
          {{ streamMode.toUpperCase() }}
        </span>
        <span
          class="rounded px-1.5 py-0.5 text-[10px] sm:text-[11px] font-medium"
          :class="
            camera.is_running
              ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
              : 'bg-slate-100 text-slate-600'
          "
        >
          {{ camera.is_running ? 'Online' : 'Standby' }}
        </span>
      </div>
    </div>

    <div class="relative aspect-video w-full bg-slate-950 overflow-hidden">
      <video
        ref="videoEl"
        class="absolute inset-0 h-full w-full object-cover"
        :class="{ invisible: streamError || !camera.stream_url }"
        autoplay
        muted
        playsinline
        loop
        crossorigin="anonymous"
        @error="onVideoError"
      />

      <!-- Fallback: no stream URL or failed to connect -->
      <div
        v-if="streamError || !camera.stream_url"
        class="absolute inset-0 flex flex-col items-center justify-center gap-2 text-slate-600"
      >
        <Video class="h-7 w-7 sm:h-8 sm:w-8 opacity-40" />
        <span class="text-xs opacity-50">
          {{ streamError ? 'Stream unavailable' : 'No stream configured' }}
        </span>
        <span
          v-if="camera.stream_url && streamError"
          class="text-[10px] opacity-30 px-4 text-center break-all"
        >
          {{ camera.stream_url }}
        </span>
      </div>

      <!-- Live Badge -->
      <div
        class="absolute left-2 top-2 sm:left-3 sm:top-3 z-10 flex items-center gap-1.5 rounded bg-black/60 px-1.5 py-0.5 sm:px-2 sm:py-1 text-[9px] sm:text-[10px] font-medium text-white pointer-events-none"
      >
        <Circle class="h-2 w-2 fill-red-500 text-red-500 animate-ping" />
        LIVE · {{ camera.code }}
      </div>

      <!-- Tracking Badge -->
      <div
        class="absolute right-2 top-2 sm:right-3 sm:top-3 z-10 rounded bg-black/60 px-1.5 py-0.5 sm:px-2 sm:py-1 text-[9px] sm:text-[10px] font-medium pointer-events-none"
        :class="
          displayDetections.length ? 'text-emerald-300' : 'text-slate-300'
        "
      >
        <span v-if="!compact" class="hidden xs:inline">TRACKING: </span>
        {{
          displayDetections.length
            ? `${displayDetections.length} DETECTED`
            : 'IDLE'
        }}
      </div>

      <div
        v-if="streamMode === 'direct' && directSyncWaiting"
        class="absolute left-1/2 top-2 sm:top-3 z-30 -translate-x-1/2 rounded bg-amber-500/90 px-2 py-1 text-[9px] sm:text-[10px] font-semibold text-white pointer-events-none"
      >
        SYNCING AI…
      </div>

      <!-- Bounding Box Overlay (always on top) -->
      <div class="absolute inset-0 pointer-events-none z-20">
        <DetectionBox
          v-for="(d, i) in displayDetections"
          :key="d.id ?? d.track_id ?? i"
          :detection="d"
          :compact="compact"
        />
      </div>

      <!-- Compact person count -->
      <div
        v-if="compact"
        class="absolute bottom-2 left-2 z-10 rounded bg-black/60 px-1.5 py-0.5 sm:px-2 sm:py-1 text-[9px] sm:text-[10px] font-medium text-white pointer-events-none"
      >
        {{ displayDetections.length }} detected
      </div>
    </div>

    <!-- Footer -->
    <div
      v-if="!compact"
      class="flex flex-wrap items-center gap-x-4 sm:gap-x-8 gap-y-2 sm:gap-y-3 border-t px-3 py-2 sm:px-4 sm:py-3 text-[11px] sm:text-xs"
    >
      <div>
        <p class="text-[10px] sm:text-xs text-slate-400">Active Persons</p>
        <p class="mt-0.5 font-semibold text-slate-800 text-xs sm:text-sm">
          {{ displayDetections.length }} tracked
        </p>
      </div>
      <div>
        <p class="text-[10px] sm:text-xs text-slate-400">Max Dwell Session</p>
        <p class="mt-0.5 font-medium text-slate-700 text-xs sm:text-sm">
          {{ maxDwellTime }}
        </p>
      </div>
      <div
        class="w-full sm:w-auto ml-0 sm:ml-auto flex items-center gap-2 pt-1.5 sm:pt-0 border-t sm:border-t-0 border-slate-100"
      >
        <button
          class="flex-1 sm:flex-initial flex items-center justify-center gap-1.5 rounded-md border px-2.5 py-1.5 text-slate-600 hover:bg-slate-50 transition-colors cursor-pointer text-[11px] sm:text-xs"
          @click="handleInspect"
          title="View active presence sessions JSON"
        >
          <ScanSearch class="h-3.5 w-3.5 shrink-0" />
          <span>Inspect Sessions</span>
        </button>
        <button
          class="flex-1 sm:flex-initial flex items-center justify-center gap-1.5 rounded-md px-2.5 py-1.5 font-medium text-red-500 hover:bg-red-50 transition-colors cursor-pointer text-[11px] sm:text-xs"
          @click="handleWarning"
        >
          <TriangleAlert class="h-3.5 w-3.5 shrink-0" />
          <span>Manual Warning</span>
        </button>
      </div>
    </div>
  </div>
</template>
