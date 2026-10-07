<script setup lang="ts">
import { AlertTriangle, Bell, Check, Clock } from '@lucide/vue';
import { useNotifications } from '@/composables/useNotifications';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';

// Klik-di-luar, Escape, dan fokus sekarang ditangani Popover (reka-ui),
// jadi listener window manual yang lama tidak diperlukan lagi.
const { notifications, unreadCount, markAsRead } = useNotifications();

function formatTime(timestamp: number) {
  if (!timestamp) return '-';
  const d = new Date(timestamp * 1000);
  return d.toLocaleTimeString('id-ID', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}
</script>

<template>
  <Popover>
    <PopoverTrigger as-child>
      <Button
        variant="ghost"
        size="icon-sm"
        class="relative text-slate-500 hover:text-slate-700"
        title="Notifikasi"
        aria-label="Notifikasi"
      >
        <Bell class="size-5" />
        <span
          v-if="unreadCount > 0"
          class="absolute -top-1 -right-1 flex h-4 min-w-4 animate-pulse items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-bold text-white shadow-xs"
        >
          {{ unreadCount > 99 ? '99+' : unreadCount }}
        </span>
      </Button>
    </PopoverTrigger>

    <PopoverContent
      align="end"
      :side-offset="8"
      class="w-80 overflow-hidden rounded-xl p-0 sm:w-96"
    >
      <div
        class="flex items-center justify-between border-b bg-slate-50/70 px-4 py-3"
      >
        <div class="flex items-center gap-2">
          <span class="text-sm font-semibold text-slate-800">Notifikasi</span>
          <Badge
            v-if="unreadCount > 0"
            variant="secondary"
            class="bg-rose-100 text-[11px] font-semibold text-rose-700"
          >
            {{ unreadCount }} Baru
          </Badge>
        </div>
        <span class="text-xs text-slate-400">Real-time SSE</span>
      </div>

      <div class="max-h-96 divide-y overflow-y-auto">
        <div
          v-if="notifications.length === 0"
          class="py-8 text-center text-xs text-slate-400"
        >
          Tidak ada notifikasi saat ini
        </div>

        <div
          v-for="item in notifications"
          :key="item.id"
          class="flex items-start gap-3 p-3 transition-colors hover:bg-slate-50"
          :class="!item.read ? 'bg-indigo-50/40' : ''"
        >
          <div
            class="mt-0.5 shrink-0 rounded-full bg-amber-100 p-1.5 text-amber-600"
          >
            <AlertTriangle class="h-4 w-4" />
          </div>

          <div class="min-w-0 flex-1">
            <div class="flex items-center justify-between gap-2">
              <p class="truncate text-xs font-semibold text-slate-900">
                {{ item.title }}
              </p>
              <span
                class="flex items-center gap-1 whitespace-nowrap text-[10px] text-slate-400"
              >
                <Clock class="h-3 w-3" />
                {{ formatTime(item.event_at) }}
              </span>
            </div>
            <p class="mt-1 line-clamp-2 text-xs leading-snug text-slate-600">
              {{ item.message }}
            </p>
            <div class="mt-2 flex items-center justify-between">
              <span class="font-mono text-[10px] text-slate-400">
                ID: {{ item.person_id }}
              </span>
              <Button
                v-if="!item.read"
                variant="ghost"
                size="xs"
                class="h-6 text-[11px] text-indigo-600 hover:bg-indigo-50 hover:text-indigo-800"
                @click="markAsRead(item.id)"
              >
                <Check />
                Tandai dibaca
              </Button>
            </div>
          </div>
        </div>
      </div>
    </PopoverContent>
  </Popover>
</template>
