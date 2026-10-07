<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue';
import { Bell, Check, Clock, AlertTriangle } from '@lucide/vue';
import { useNotifications } from '@/composables/useNotifications';
import { Badge } from '@/components/ui/badge';

const { notifications, unreadCount, markAsRead } = useNotifications();
const isOpen = ref(false);
const dropdownRef = ref<HTMLElement | null>(null);

function toggleOpen() {
  isOpen.value = !isOpen.value;
}

function closeDropdown() {
  isOpen.value = false;
}

function handleClickOutside(event: MouseEvent) {
  if (dropdownRef.value && !dropdownRef.value.contains(event.target as Node)) {
    closeDropdown();
  }
}

function formatTime(timestamp: number) {
  if (!timestamp) return '-';
  const d = new Date(timestamp * 1000);
  return d.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

onMounted(() => {
  window.addEventListener('click', handleClickOutside);
});

onUnmounted(() => {
  window.removeEventListener('click', handleClickOutside);
});
</script>

<template>
  <div class="relative" ref="dropdownRef">
    <button
      @click.stop="toggleOpen"
      class="relative rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-700 transition-colors cursor-pointer"
      title="Notifikasi"
    >
      <Bell class="h-5 w-5" />
      <span
        v-if="unreadCount > 0"
        class="absolute -top-1 -right-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-bold text-white shadow-xs animate-pulse"
      >
        {{ unreadCount > 99 ? '99+' : unreadCount }}
      </span>
    </button>

    <!-- Dropdown Content -->
    <div
      v-if="isOpen"
      class="absolute right-0 mt-2 w-80 sm:w-96 rounded-xl border border-slate-200 bg-white shadow-xl z-50 overflow-hidden text-slate-800 animate-in fade-in slide-in-from-top-2 duration-150"
    >
      <div class="flex items-center justify-between border-b border-slate-100 bg-slate-50/70 px-4 py-3">
        <div class="flex items-center gap-2">
          <span class="font-semibold text-sm text-slate-800">Notifikasi</span>
          <Badge v-if="unreadCount > 0" variant="secondary" class="bg-rose-100 text-rose-700 text-[11px] font-semibold">
            {{ unreadCount }} Baru
          </Badge>
        </div>
        <span class="text-xs text-slate-400">Real-time SSE</span>
      </div>

      <div class="max-h-96 overflow-y-auto divide-y divide-slate-100">
        <div v-if="notifications.length === 0" class="py-8 text-center text-xs text-slate-400">
          Tidak ada notifikasi saat ini
        </div>

        <div
          v-for="item in notifications"
          :key="item.id"
          class="p-3 transition-colors hover:bg-slate-50 flex items-start gap-3"
          :class="!item.read ? 'bg-indigo-50/40' : ''"
        >
          <div class="mt-0.5 shrink-0 rounded-full p-1.5 bg-amber-100 text-amber-600">
            <AlertTriangle class="h-4 w-4" />
          </div>

          <div class="min-w-0 flex-1">
            <div class="flex items-center justify-between gap-2">
              <p class="text-xs font-semibold text-slate-900 truncate">
                {{ item.title }}
              </p>
              <span class="text-[10px] text-slate-400 whitespace-nowrap flex items-center gap-1">
                <Clock class="h-3 w-3" />
                {{ formatTime(item.event_at) }}
              </span>
            </div>
            <p class="mt-1 text-xs text-slate-600 leading-snug line-clamp-2">
              {{ item.message }}
            </p>
            <div class="mt-2 flex items-center justify-between">
              <span class="text-[10px] font-mono text-slate-400">
                ID: {{ item.person_id }}
              </span>
              <button
                v-if="!item.read"
                @click.stop="markAsRead(item.id)"
                class="text-[11px] font-medium text-indigo-600 hover:text-indigo-800 flex items-center gap-1 cursor-pointer"
              >
                <Check class="h-3 w-3" />
                Tandai dibaca
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
