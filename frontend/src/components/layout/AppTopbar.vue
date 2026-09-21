<script setup>
import { Bell, LayoutGrid, Menu, Settings } from '@lucide/vue';

defineProps({
  crumbs: {
    type: Array,
    default: () => ['Dashboard', 'Overview'],
  },
});

defineEmits(['toggle-sidebar']);
</script>

<template>
  <header class="flex h-14 items-center justify-between border-b bg-white px-3 sm:px-6">
    <!-- Left: Hamburger button + Breadcrumbs -->
    <div class="flex items-center gap-1.5 sm:gap-2 text-xs sm:text-sm text-slate-500 min-w-0">
      <button
        class="mr-1 -ml-1 rounded-lg p-1.5 text-slate-600 hover:bg-slate-100 md:hidden"
        @click="$emit('toggle-sidebar')"
        aria-label="Toggle navigation menu"
      >
        <Menu class="h-5 w-5" />
      </button>

      <LayoutGrid class="h-4 w-4 shrink-0 text-slate-400 hidden xs:block" />

      <!-- Mobile crumb: only current view name -->
      <span class="font-medium text-slate-900 truncate sm:hidden">
        {{ crumbs[crumbs.length - 1] }}
      </span>

      <!-- Desktop crumbs: full path -->
      <div class="hidden sm:flex sm:items-center sm:gap-1.5">
        <template v-for="(crumb, i) in crumbs" :key="crumb">
          <span :class="i === crumbs.length - 1 ? 'font-medium text-slate-900' : ''">{{ crumb }}</span>
          <span v-if="i < crumbs.length - 1" class="text-slate-300">/</span>
        </template>
      </div>
    </div>

    <!-- Right: Status Badge + Action Buttons -->
    <div class="flex items-center gap-2 sm:gap-3 shrink-0">
      <!-- <span
        class="flex items-center gap-1.5 rounded-full bg-emerald-50 px-2 sm:px-2.5 py-0.5 sm:py-1 text-[11px] sm:text-xs font-medium text-emerald-700 border border-emerald-200"
      >
        <span class="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
        <span class="hidden sm:inline">AI Engine </span>Online
      </span> -->

      <button class="rounded-lg p-1.5 text-slate-400 hover:bg-slate-50 hover:text-slate-600 transition-colors">
        <Bell class="h-4 w-4 sm:h-5 sm:w-5" />
      </button>

      <div
        class="h-7 w-7 sm:h-8 sm:w-8 rounded-full bg-indigo-100 text-center text-xs font-semibold leading-7 sm:leading-8 text-indigo-600 shrink-0"
      >
        AD
      </div>
    </div>
  </header>
</template>
