<script setup>
import AppSidebar from '@/components/layout/AppSidebar.vue';
import AppTopbar from '@/components/layout/AppTopbar.vue';

defineProps({
  crumbs: {
    type: Array,
    default: () => ['Dashboard', 'Overview'],
  },
});
</script>

<template>
  <div class="flex h-screen bg-slate-50">
    <AppSidebar />
    <div class="flex flex-1 flex-col overflow-hidden">
      <AppTopbar :crumbs="crumbs" />
      <main class="flex-1 overflow-y-auto p-6">
        <slot />
      </main>
    </div>
  </div>
</template>
