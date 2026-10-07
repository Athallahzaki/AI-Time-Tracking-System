import { computed, onMounted, onUnmounted, ref } from 'vue';
import { apiFetch } from './useAuth';

export interface NotificationItem {
  id: number;
  person_id: string;
  type: string;
  title: string;
  message: string;
  event_at: number;
  read: boolean;
  created_at: string;
  payload?: any;
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
      notifications.value = data.notifications || [];
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
        if (item) item.read = true;
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
        const data: NotificationItem = JSON.parse(e.data);
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
