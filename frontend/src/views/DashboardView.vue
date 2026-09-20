<script setup>
import { ref } from 'vue';
import DashboardLayout from '@/layouts/DashboardLayout.vue';
import DashboardHeader from '@/components/dashboard/DashboardHeader.vue';
import StatsRow from '@/components/dashboard/StatsRow.vue';
import LiveFeedSection from '@/components/dashboard/LiveFeedSection.vue';
import { useDetectionStream } from '@/composables/useDetectionStream';
import BreakAllowancePanel from '@/components/dashboard/BreakAllowancePanel.vue';
import UnidentifiedAlertPanel from '@/components/dashboard/UnidentifiedAlertPanel.vue';
import ManualCorrectionPanel from '@/components/dashboard/ManualCorrectionPanel.vue';

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
      <BreakAllowancePanel />
      <UnidentifiedAlertPanel />
      <ManualCorrectionPanel ref="correctionPanelref" />
    </div>
  </DashboardLayout>
</template>
