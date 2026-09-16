<script setup>
import { ref, watch, onMounted, onBeforeUnmount, computed } from 'vue';
import Hls from 'hls.js';
import { Circle, ScanSearch, TriangleAlert, Video, Wifi } from '@lucide/vue';
import DetectionBox from './DetectionBox.vue';

const props = defineProps({
  camera: { type: Object, required: true },
  compact: { type: Boolean, default: false },
});

const videoEl = ref(null);
const streamError = ref(false);
const streamMode = ref(''); // 'webrtc' | 'hls' | 'direct' | ''

let pc = null;    // RTCPeerConnection for WebRTC
let hls = null;   // Hls instance for HLS

const maxDwellTime = computed(() => {
  if (!props.camera.detections || props.camera.detections.length === 0) return 'Inactive';
  const extras = props.camera.detections.map((d) => d.extra).filter(Boolean);
  return extras.length > 0 ? extras[0] : 'Active';
});

// ─── Stream type detection ────────────────────────────────────────────────────

function isWhepUrl(url) {
  return url && (url.endsWith('/whep') || url.includes('/whep?'));
}

function isHlsUrl(url) {
  return url && url.includes('.m3u8');
}

// ─── WebRTC / WHEP ────────────────────────────────────────────────────────────

const WEBRTC_PLAYOUT_DELAY = 0.8; //800 ms

async function startWhep(url) {
  teardown();
  streamError.value = false;
  streamMode.value = 'webrtc';

  try {
    pc = new RTCPeerConnection({
      iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
    });

    // Request video and audio as recvonly transceivers.
    const videoTransceiver = pc.addTransceiver('video', {
      direction: 'recvonly',
    });

    const audioTransceiver = pc.addTransceiver('audio', {
      direction: 'recvonly',
    });

    // Ask the browser's WebRTC receiver to maintain ~200ms of
    // playout delay. This is a rolling playback delay, unlike
    // simply delaying assignment of srcObject.
    try {
      if ('playoutDelayHint' in videoTransceiver.receiver) {
        videoTransceiver.receiver.playoutDelayHint =
          WEBRTC_PLAYOUT_DELAY;
      }

      if ('playoutDelayHint' in audioTransceiver.receiver) {
        audioTransceiver.receiver.playoutDelayHint =
          WEBRTC_PLAYOUT_DELAY;
      }
    } catch (err) {
      console.warn(
        '[WebRTC] Could not set playout delay hint:',
        err
      );
    }

    // Attach incoming tracks to the video element.
    pc.ontrack = (event) => {
      if (
        event.streams &&
        event.streams[0] &&
        videoEl.value
      ) {
        videoEl.value.srcObject = event.streams[0];

        videoEl.value.play().catch((err) => {
          console.warn('[WebRTC] Autoplay failed:', err);
        });
      }
    };

    pc.onconnectionstatechange = () => {
      if (
        pc &&
        (
          pc.connectionState === 'failed' ||
          pc.connectionState === 'closed'
        )
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
      throw new Error(
        `WHEP signaling failed: HTTP ${response.status}`
      );
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
  if (videoEl.value) {
    videoEl.value.src = url;
    videoEl.value.load();
  }
}

// ─── Teardown helpers ─────────────────────────────────────────────────────────

function teardownWebRtc() {
  if (pc) { pc.close(); pc = null; }
  if (videoEl.value) videoEl.value.srcObject = null;
}

function teardownHls() {
  if (hls) { hls.destroy(); hls = null; }
}

function teardown() {
  teardownWebRtc();
  teardownHls();
}

// ─── Route to correct player ──────────────────────────────────────────────────

function attachStream(url) {
  if (!url) { teardown(); streamMode.value = ''; return; }
  if (isWhepUrl(url))      startWhep(url);
  else if (isHlsUrl(url))  startHls(url);
  else                     startDirect(url);
}

watch(() => props.camera.stream_url, (newUrl) => attachStream(newUrl));

onMounted(() => { if (props.camera.stream_url) attachStream(props.camera.stream_url); });
onBeforeUnmount(() => teardown());

function onVideoError() {
  if (streamMode.value !== 'webrtc') streamError.value = true;
}

function handleInspect() {
  window.open('/api/attendance/active', '_blank');
}

function handleWarning() {
  alert(`Manual warning signal dispatched for ${props.camera.name} (${props.camera.code})`);
}
</script>

<template>
  <div class="overflow-hidden rounded-xl border bg-white shadow-xs transition-all">
    <!-- Card Header -->
    <div class="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-2.5">
      <div class="flex items-center gap-2 text-sm font-medium text-slate-800">
        <span
          class="h-2 w-2 rounded-full"
          :class="camera.is_running !== false ? 'bg-emerald-500 animate-pulse' : 'bg-slate-400'"
        ></span>
        {{ camera.code }}: {{ camera.name }}
      </div>
      <div v-if="!compact" class="flex items-center gap-3 text-xs text-slate-500">
        <span class="font-medium text-slate-700">{{ camera.fps }} FPS</span>
        <span
          v-if="streamMode"
          class="rounded px-1.5 py-0.5 text-[11px] font-medium bg-sky-50 text-sky-700 border border-sky-200"
          :title="camera.stream_url"
        >
          {{ streamMode.toUpperCase() }}
        </span>
        <span
          class="rounded px-1.5 py-0.5 text-[11px] font-medium"
          :class="camera.is_running ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-slate-100 text-slate-600'"
        >
          {{ camera.is_running ? 'Online' : 'Standby' }}
        </span>
      </div>
    </div>

    <!-- Video Feed Viewport -->
    <div class="relative aspect-video w-full bg-slate-950 overflow-hidden">

      <!-- Video element — srcObject is set by WebRTC, src by HLS/direct.
           Always in DOM so the ref is available immediately on mount. -->
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
        <Video class="h-8 w-8 opacity-40" />
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
        class="absolute left-3 top-3 z-10 flex items-center gap-1.5 rounded bg-black/60 px-2 py-1 text-[10px] font-medium text-white pointer-events-none"
      >
        <Circle class="h-2 w-2 fill-red-500 text-red-500 animate-ping" />
        LIVE · {{ camera.code }}
      </div>

      <!-- Tracking Badge -->
      <div
        class="absolute right-3 top-3 z-10 rounded bg-black/60 px-2 py-1 text-[10px] font-medium pointer-events-none"
        :class="camera.detections?.length ? 'text-emerald-300' : 'text-slate-300'"
      >
        <span v-if="!compact">TRACKING: </span>
        {{ camera.detections?.length ? `${camera.detections.length} DETECTED` : 'IDLE' }}
      </div>

      <!-- Bounding Box Overlay (always on top) -->
      <div class="absolute inset-0 pointer-events-none z-20">
        <DetectionBox
          v-for="(d, i) in camera.detections"
          :key="d.id ?? d.track_id ?? i"
          :detection="d"
          :compact="compact"
        />
      </div>

      <!-- Compact person count -->
      <div
        v-if="compact"
        class="absolute bottom-2 left-2 z-10 rounded bg-black/60 px-2 py-1 text-[10px] font-medium text-white pointer-events-none"
      >
        {{ camera.detections?.length || 0 }} detected
      </div>
    </div>

    <!-- Footer -->
    <div
      v-if="!compact"
      class="flex flex-wrap items-center gap-x-8 gap-y-3 border-t px-4 py-3 text-xs"
    >
      <div>
        <p class="text-slate-400">Active Persons</p>
        <p class="mt-0.5 font-semibold text-slate-800">
          {{ camera.detections?.length || 0 }} tracked
        </p>
      </div>
      <div>
        <p class="text-slate-400">Max Dwell Session</p>
        <p class="mt-0.5 font-medium text-slate-700">{{ maxDwellTime }}</p>
      </div>
      <div class="ml-auto flex items-center gap-2">
        <button
          class="flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-slate-600 hover:bg-slate-50 transition-colors cursor-pointer"
          @click="handleInspect"
          title="View active presence sessions JSON"
        >
          <ScanSearch class="h-3.5 w-3.5" />
          Inspect Sessions
        </button>
        <button
          class="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 font-medium text-red-500 hover:bg-red-50 transition-colors cursor-pointer"
          @click="handleWarning"
        >
          <TriangleAlert class="h-3.5 w-3.5" />
          Manual Warning
        </button>
      </div>
    </div>
  </div>
</template>
