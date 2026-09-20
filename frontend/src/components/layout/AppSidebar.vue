<script setup>
import { Bell, Building2, ChevronsUpDown, FileText, History, LayoutDashboard, Settings, ShieldCheck, Users, Video, X } from '@lucide/vue';
import { RouterLink, useRoute } from 'vue-router';
import { Badge } from '../ui/badge';

defineProps({
  isOpen: {
    type: Boolean,
    default: false,
  },
});

defineEmits(['close']);

const route = useRoute();

const mainNav = [
  { label: 'Dashboard', icon: LayoutDashboard, to: '/' },
  { label: 'Live Monitoring', icon: Video, to: '/#' },
  { label: 'Employees', icon: Users, to: '/#' },
  { label: 'Reports', icon: FileText, to: '/#' },
  { label: 'Notifications', icon: Bell, to: '/#' },
];

const isActive = (path) => route.path === path;
</script>

<template>
  <!-- Backdrop for mobile drawer -->
  <div
    v-if="isOpen"
    class="fixed inset-0 z-40 bg-slate-900/50 backdrop-blur-xs transition-opacity md:hidden"
    @click="$emit('close')"
  />

  <aside
    class="fixed inset-y-0 left-0 z-50 flex h-full w-64 flex-col border-r bg-white transition-transform duration-200 ease-in-out md:static md:h-screen md:translate-x-0"
    :class="isOpen ? 'translate-x-0 shadow-2xl' : '-translate-x-full md:translate-x-0'"
  >
    <!-- Brand / Header -->
    <div class="flex items-center justify-between border-b px-4 py-4 md:border-b-0 md:px-5 md:py-5">
      <div class="flex items-center gap-2.5">
        <div class="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-900">
          <ShieldCheck class="h-5 w-5 text-white" />
        </div>
        <div class="leading-tight">
          <p class="text-sm font-semibold text-slate-900">Hotel Murah</p>
          <p class="text-xs text-slate-500">AI Time Tracking</p>
        </div>
      </div>

      <!-- Mobile Close Button -->
      <button
        class="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 md:hidden"
        @click="$emit('close')"
        aria-label="Close menu"
      >
        <X class="h-5 w-5" />
      </button>
    </div>

    <!-- Navigation -->
    <nav class="flex-1 space-y-1 overflow-y-auto px-3 pt-3">
      <RouterLink
        v-for="item in mainNav"
        :key="item.label"
        :to="item.to"
        class="flex items-center justify-between rounded-lg px-3 py-2 text-sm font-medium transition-colors"
        :class="
          isActive(item.to)
            ? 'bg-indigo-50 text-indigo-600'
            : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
        "
        @click="$emit('close')"
      >
        <span class="flex items-center gap-3">
          <component :is="item.icon" class="h-4 w-4" />
          {{ item.label }}
        </span>
        <Badge v-if="item.badge" variant="secondary" class="h-5 px-1.5 text-xs">
          {{ item.badge }}
        </Badge>
      </RouterLink>
    </nav>

    <!-- User Profile Footer -->
    <div class="flex items-center gap-3 border-t px-4 py-3.5">
      <div class="flex h-8 w-8 items-center justify-center rounded-full bg-indigo-100 text-xs font-semibold text-indigo-600">
        AD
      </div>
      <div class="min-w-0 flex-1 leading-tight">
        <p class="truncate text-sm font-medium text-slate-900">Administrator</p>
        <p class="truncate text-xs text-slate-500">admin@hotelmurah.com</p>
      </div>
      <ChevronsUpDown class="h-4 w-4 shrink-0 text-slate-400" />
    </div>
  </aside>
</template>
