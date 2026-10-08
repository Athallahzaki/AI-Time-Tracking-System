import { computed, onMounted, onUnmounted, ref } from 'vue';
import { apiFetch } from './useAuth';

export interface NotificationItem {
  id: number;
  person_id: string;
  type: string;
  title: string;
  message: string;
  event_at: number;
  /** Turunan dari read_at; backend tidak mengirim field `read`. */
  read: boolean;
  read_at?: number | null;
  created_at: number;
  payload?: any;
}

// Backend (/api/notifications dan SSE) mengirim `read_at` (epoch atau null),
// bukan `read`. Tanpa pemetaan ini semua notifikasi terlihat belum dibaca
// setelah halaman dimuat ulang.
function normalize(raw: any): NotificationItem {
  return { ...raw, read: raw?.read === true || (raw?.read_at !== null && raw?.read_at !== undefined) };
}

const notifications = ref<NotificationItem[]>([]);
const isLoading = ref<boolean>(false);
const error = ref<string | null>(null);

let eventSource: EventSource | null = null;
let listenerCount = 0;

export function useNotifications() {
  const unreadCount = computed(
    () => notifications.value.filter((n) => !n.read).length
  );

  async function fetchNotifications(limit = 50): Promise<void> {
    isLoading.value = true;
    error.value = null;
    try {
      const res = await apiFetch(`/api/notifications?limit=${limit}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      notifications.value = (data.notifications || []).map(normalize);
    } catch (err: any) {
      error.value = err.message || 'Gagal memuat notifikasi';
    } finally {
      isLoading.value = false;
    }
  }

  async function markAsRead(id: number): Promise<void> {
    try {
      const res = await apiFetch(`/api/notifications/${id}/read`, {
        method: 'PATCH',
      });
      if (res.ok) {
        const item = notifications.value.find((n) => n.id === id);
        if (item) {
          item.read = true;
          item.read_at = Date.now() / 1000;
        }
      }
    } catch (err) {
      console.error('Failed to mark notification as read:', err);
    }
  }

  function connectSse(): void {
    if (eventSource) return;

    // Pastikan koneksi SSE aktif
    eventSource = new EventSource('/api/notifications/stream');

    eventSource.addEventListener('notification', (e: MessageEvent) => {
      try {
        const data: NotificationItem = normalize(JSON.parse(e.data));
        const existingIdx = notifications.value.findIndex((n) => n.id === data.id);
        if (existingIdx !== -1) {
          notifications.value[existingIdx] = data;
        } else {
          notifications.value.unshift(data);
        }
      } catch (err) {
        console.error('Error parsing SSE notification:', err);
      }
    });

    eventSource.onerror = (err) => {
      console.warn('SSE notification stream reconnecting...', err);
    };
  }

  function disconnectSse(): void {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
  }

  function init(): void {
    fetchNotifications();
    connectSse();
  }

  // Jika dipanggil di dalam setup komponen, hubungkan SSE dan lifecycle
  try {
    onMounted(() => {
      listenerCount++;
      if (listenerCount === 1) {
        init();
      }
    });

    onUnmounted(() => {
      listenerCount--;
      if (listenerCount <= 0) {
        listenerCount = 0;
        disconnectSse();
      }
    });
  } catch {
    // Dipanggil di luar setup context
  }

  return {
    notifications,
    unreadCount,
    isLoading,
    error,
    fetchNotifications,
    markAsRead,
    connectSse,
    disconnectSse,
  };
}
