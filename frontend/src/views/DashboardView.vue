<script setup>
import { ref } from 'vue';
import DashboardLayout from '@/layouts/DashboardLayout.vue';
import DashboardHeader from '@/components/dashboard/DashboardHeader.vue';
import StatsRow from '@/components/dashboard/StatsRow.vue';
import LiveFeedSection from '@/components/dashboard/LiveFeedSection.vue';
import { useDetectionStream } from '@/composables/useDetectionStream';

const refreshInterval = ref('5');
const { stats, isConnected, isStreaming, reconnect } = useDetectionStream();

function handleExport() {
  window.open('/api/attendance/events', '_blank');
}

function handleConfigure() {
  window.open('/api/cameras', '_blank');
}
</script>

<template>
  <DashboardLayout :crumbs="['Dashboard', 'Overview']">
    <div class="space-y-5">
      <DashboardHeader
        v-model:refresh-interval="refreshInterval"
        @export="handleExport"
        @configure="handleConfigure"
      />
      <StatsRow :stats="stats" />
      <LiveFeedSection />
    </div>
  </DashboardLayout>
</template>
