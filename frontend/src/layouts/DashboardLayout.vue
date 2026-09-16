<script setup>
import { ref } from 'vue';
import AppSidebar from '@/components/layout/AppSidebar.vue';
import AppTopbar from '@/components/layout/AppTopbar.vue';

defineProps({
  crumbs: {
    type: Array,
    default: () => ['Dashboard', 'Overview'],
  },
});

const isSidebarOpen = ref(false);

function toggleSidebar() {
  isSidebarOpen.value = !isSidebarOpen.value;
}

function closeSidebar() {
  isSidebarOpen.value = false;
}
</script>

<template>
  <div class="flex h-screen bg-slate-50 overflow-hidden">
    <!-- Sidebar with mobile drawer support -->
    <AppSidebar :is-open="isSidebarOpen" @close="closeSidebar" />

    <div class="flex flex-1 flex-col overflow-hidden min-w-0">
      <AppTopbar :crumbs="crumbs" @toggle-sidebar="toggleSidebar" />
      <main class="flex-1 overflow-y-auto p-3.5 sm:p-5 md:p-6">
        <slot />
      </main>
    </div>
  </div>
</template>
