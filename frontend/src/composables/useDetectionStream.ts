import { ref, reactive, onMounted, onUnmounted } from 'vue';
import { cameras as initialCameras } from '@/data/cameras';

export interface DetectionItem {
  id?: string | number;
  label: string;
  sub: string;
  conf: string;
  extra?: string;
  color: 'emerald' | 'amber' | 'red' | 'cyan';
  top: string;
  left: string;
  width: string;
  height: string;
  warning?: boolean;
  track_id?: number;
}

export interface CameraItem {
  id: string;
  code: string;
  name: string;
  src: string;
  source_uri?: string;
  fps: string | number;
  latency: string;
  model: string;
  fov: string;
  streamStatus: string;
  activity: string;
  trackingIds: string;
  maxSession: string;
  is_running?: boolean;
  active_people?: number;
  detections: DetectionItem[];
}

export interface DashboardStats {
  activeFacilities: number;
  totalFacilities: number;
  activeUsers: number;
  totalUsage: string;
  avgSession: string;
  exceededDuration: number;
}

interface BackendBbox {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

interface BackendPerson {
  track_id: number;
  bbox: BackendBbox;
  confidence: number;
  state?: string;
  dwell_time?: number;
  presence_status?: string;
  identity?: string | null;
  similarity?: number;
  session_elapsed?: number;
}

interface BackendDetectionPayload {
  camera_id: string;
  frame_id: number;
  width: number;
  height: number;
  fps: number;
  people: BackendPerson[];
}

function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}m ${rem}s`;
}

// Deep clone initial cameras to make reactive state
const liveCameras = reactive<CameraItem[]>(
  JSON.parse(JSON.stringify(initialCameras))
);

const liveStats = reactive<DashboardStats>({
  activeFacilities: 1,
  totalFacilities: 4,
  activeUsers: 0,
  totalUsage: '0s',
  avgSession: '0s',
  exceededDuration: 0,
});

export function useDetectionStream() {
  const isConnected = ref(false);
  const isStreaming = ref(false);
  const lastUpdated = ref<Date | null>(null);
  const connectionError = ref<string | null>(null);

  let eventSource: EventSource | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let statsPollTimer: ReturnType<typeof setInterval> | null = null;
  let activeClientsCount = 0;

  async function fetchCameras() {
    try {
      const res = await fetch('/api/cameras');
      if (!res.ok) return;
      const json = await res.json();
      if (json.status === 'success' && Array.isArray(json.cameras)) {
        json.cameras.forEach((backendCam: any) => {
          const match = liveCameras.find((c) => c.id === backendCam.id);
          if (match) {
            match.name = backendCam.name || match.name;
            match.code = backendCam.code || match.code;
            match.fov = backendCam.fov || match.fov;
            match.model = backendCam.model || match.model;
            match.streamStatus = backendCam.streamStatus || match.streamStatus;
            match.is_running = backendCam.is_running;
          }
        });
      }
    } catch (err) {
      console.debug('[API] Cameras fetch fallback to local defaults:', err);
    }
  }

  async function fetchStats() {
    try {
      const res = await fetch('/api/stats');
      if (!res.ok) return;
      const json = await res.json();
      if (json.status === 'success' && json.data) {
        Object.assign(liveStats, json.data);
      }
    } catch (err) {
      console.debug('[API] Stats fetch skipped:', err);
    }
  }

  async function switchCameraSource(cameraId: string, sourceUri: string) {
    try {
      const res = await fetch(`/api/cameras/${cameraId}/source`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_uri: sourceUri }),
      });
      return await res.json();
    } catch (err) {
      console.error('[API] Failed to switch source:', err);
      throw err;
    }
  }

  function connect() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }

    const apiUrl =
      import.meta.env.VITE_API_URL ||
      (window.location.port === '5173'
        ? '/api/detections/stream'
        : 'http://localhost:8000/api/detections/stream');

    try {
      eventSource = new EventSource(apiUrl);

      eventSource.onopen = () => {
        isConnected.value = true;
        connectionError.value = null;
        console.log('[SSE] Connected to AI Vision detection stream:', apiUrl);
      };

      const handlePayload = (rawPayload: string) => {
        try {
          const data: BackendDetectionPayload = JSON.parse(rawPayload);
          if (!data || !data.camera_id) return;

          isStreaming.value = true;
          lastUpdated.value = new Date();

          const targetCam = liveCameras.find((c) => c.id === data.camera_id);
          if (!targetCam) return;

          const frameW = data.width || 1920;
          const frameH = data.height || 1080;

          // Convert backend detections to frontend percentage bounding boxes
          const mappedDetections: DetectionItem[] = (data.people || []).map(
            (person) => {
              const bbox = person.bbox || { x1: 0, y1: 0, x2: 0, y2: 0 };

              const x1 = Math.max(0, Math.min(frameW, bbox.x1));
              const y1 = Math.max(0, Math.min(frameH, bbox.y1));
              const x2 = Math.max(x1, Math.min(frameW, bbox.x2));
              const y2 = Math.max(y1, Math.min(frameH, bbox.y2));

              const leftPct = (x1 / frameW) * 100;
              const topPct = (y1 / frameH) * 100;
              const widthPct = ((x2 - x1) / frameW) * 100;
              const heightPct = ((y2 - y1) / frameH) * 100;

              const label = person.identity
                ? `Emp #${person.identity}`
                : `ID #${person.track_id}`;

              const sub = person.presence_status || person.state || 'TRACKED';

              const confVal =
                person.confidence != null
                  ? person.confidence <= 1
                    ? person.confidence * 100
                    : person.confidence
                  : 95;
              const conf = `${Math.round(confVal)}%`;

              const elapsed = person.session_elapsed ?? person.dwell_time ?? 0;
              let extra = formatDuration(elapsed);

              let color: 'emerald' | 'amber' | 'red' | 'cyan' = 'emerald';
              let warning = false;

              if (person.presence_status === 'LIMIT') {
                color = 'red';
                warning = true;
                extra += ' (LIMIT REACHED)';
              } else if (person.presence_status === 'WARNING') {
                color = 'amber';
                warning = true;
                extra += ' (LIMIT NEAR)';
              } else if (person.presence_status === 'CONFIRMED') {
                color = 'emerald';
              } else {
                color = 'cyan';
              }

              return {
                id: person.track_id,
                track_id: person.track_id,
                label,
                sub,
                conf,
                extra,
                color,
                warning,
                left: `${leftPct.toFixed(2)}%`,
                top: `${topPct.toFixed(2)}%`,
                width: `${widthPct.toFixed(2)}%`,
                height: `${heightPct.toFixed(2)}%`,
              };
            }
          );

          targetCam.detections = mappedDetections;
          if (data.fps) {
            targetCam.fps = data.fps.toFixed(1);
          }
          targetCam.streamStatus = 'Online & Streaming';

          if (mappedDetections.length > 0) {
            targetCam.trackingIds = mappedDetections
              .map((d) => `#TRK-${d.track_id}`)
              .join(', ');

            const maxElapsed = Math.max(
              ...data.people.map(
                (p) => p.session_elapsed ?? p.dwell_time ?? 0
              )
            );
            targetCam.maxSession = formatDuration(maxElapsed);
          } else {
            targetCam.trackingIds = '—';
            targetCam.maxSession = 'Inactive';
          }
        } catch (err) {
          console.error('[SSE] Failed to parse detection message:', err);
        }
      };

      eventSource.addEventListener('detection', (event: MessageEvent) => {
        handlePayload(event.data);
      });

      eventSource.onmessage = (event: MessageEvent) => {
        handlePayload(event.data);
      };

      eventSource.onerror = (err) => {
        console.warn('[SSE] Disconnected from AI Engine, retrying in 3s...', err);
        isConnected.value = false;
        connectionError.value = 'Disconnected from AI Engine';
        if (eventSource) {
          eventSource.close();
          eventSource = null;
        }
        scheduleReconnect();
      };
    } catch (err: any) {
      connectionError.value = err?.message || 'Failed to initialize EventSource';
      scheduleReconnect();
    }
  }

  function scheduleReconnect() {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(() => {
      connect();
    }, 3000);
  }

  onMounted(() => {
    activeClientsCount++;
    fetchCameras();
    fetchStats();
    if (!eventSource) {
      connect();
    }
    if (!statsPollTimer) {
      statsPollTimer = setInterval(fetchStats, 3000);
    }
  });

  onUnmounted(() => {
    activeClientsCount--;
    if (activeClientsCount <= 0) {
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      if (statsPollTimer) {
        clearInterval(statsPollTimer);
        statsPollTimer = null;
      }
    }
  });

  return {
    cameras: liveCameras,
    stats: liveStats,
    isConnected,
    isStreaming,
    lastUpdated,
    connectionError,
    reconnect: connect,
    fetchCameras,
    fetchStats,
    switchCameraSource,
  };
}
