import { ref, reactive, onMounted, onUnmounted } from 'vue';

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
  stream_url?: string;
  fps: string | number;
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

// Reactive list of cameras dynamically loaded from backend GET /api/cameras
const liveCameras = reactive<CameraItem[]>([]);

const liveStats = reactive<DashboardStats>({
  activeFacilities: 0,
  totalFacilities: 0,
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
        const backendCams = json.cameras;

        // Remove cameras no longer in backend config
        for (let i = liveCameras.length - 1; i >= 0; i--) {
          if (!backendCams.some((bc: any) => bc.id === liveCameras[i].id)) {
            liveCameras.splice(i, 1);
          }
        }

        // Add or update cameras
        backendCams.forEach((backendCam: any) => {
          let match = liveCameras.find((c) => c.id === backendCam.id);
          if (!match) {
            match = {
              id: backendCam.id,
              code: backendCam.code || backendCam.id.toUpperCase(),
              name: backendCam.name || backendCam.id,
              stream_url: backendCam.stream_url || '',
              fps: backendCam.fps || 0,
              is_running: backendCam.is_running || false,
              active_people: backendCam.active_people || 0,
              detections: [],
            };
            liveCameras.push(match);
          } else {
            match.name = backendCam.name || match.name;
            match.code = backendCam.code || match.code;
            match.stream_url = backendCam.stream_url || match.stream_url;
            match.is_running = backendCam.is_running;
            if (backendCam.fps !== undefined) match.fps = backendCam.fps;
          }
        });
      }
    } catch (err) {
      console.debug('[API] Cameras fetch error:', err);
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
      };

      const handlePayload = (rawPayload: string) => {
        try {
          const data: BackendDetectionPayload = JSON.parse(rawPayload);
          if (!data || !data.camera_id) return;

          isStreaming.value = true;
          lastUpdated.value = new Date();

          let targetCam = liveCameras.find((c) => c.id === data.camera_id);
          if (!targetCam) {
            targetCam = {
              id: data.camera_id,
              code: data.camera_id.toUpperCase(),
              name: data.camera_id,
              stream_url: '',
              fps: data.fps || 0,
              is_running: true,
              active_people: 0,
              detections: [],
            };
            liveCameras.push(targetCam);
          }

          const frameW = data.width || 1920;
          const frameH = data.height || 1080;

          // Convert backend detections to frontend percentage coordinates
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
          targetCam.active_people = mappedDetections.length;
          targetCam.is_running = true;
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
      statsPollTimer = setInterval(() => {
        fetchStats();
        fetchCameras();
      }, 5000);
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
  };
}
