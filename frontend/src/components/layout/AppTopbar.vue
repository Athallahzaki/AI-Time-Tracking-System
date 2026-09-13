<script setup>
import { Bell, LayoutGrid, Settings } from '@lucide/vue';

defineProps({
  crumbs: {
    type: Array,
    default: () => ['Dashboard', 'Overview'],
  },
});
</script>

<template>
  <header class="flex h-14 items-center justify-between border-b bg-white px-6">
    <div class="flex items-center gap-2 text-sm text-slate-500">
      <LayoutGrid class="h-4 w-4" />
      <template v-for="(crumb, i) in crumbs" :key="crumb">
        <span
          :class="i === crumbs.length - 1 ? 'font-medium text-slate-900' : ''"
          >{{ crumb }}</span
        >
        <span v-if="i < crumbs.length - 1">/</span>
      </template>
    </div>

    <div class="flex items-center gap-4">
      <span
        class="flex items-center gap-1.5 rounded-full bg-green-50 px-3 py-1 text-xs font-medium text-green-700"
      >
        <span class="h-1.5 w-1.5 rounded-full bg-green-500"></span>
        AI Engine Online (v2.4.3)
      </span>
      <button class="text-slate-400 hover:text-slate-600">
        <Bell class="h-5 w-5" />
      </button>
      <button class="text-slate-400 hover:text-slate-600">
        <Settings class="h-5 w-5" />
      </button>
      <div
        class="h-8 w-8 rounded-full bg-indigo-100 text-center text-xs font-semibold leading-8 text-indigo-600"
      >
        AD
      </div>
    </div>
  </header>
</template>
