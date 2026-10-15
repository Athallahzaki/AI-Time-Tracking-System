<script setup>
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import DashboardLayout from '@/layouts/DashboardLayout.vue';
import DashboardHeader from '@/components/dashboard/DashboardHeader.vue';
import StatsRow from '@/components/dashboard/StatsRow.vue';
import LiveFeedSection from '@/components/dashboard/LiveFeedSection.vue';
import { useDetectionStream } from '@/composables/useDetectionStream';
import BreakAllowancePanel from '@/components/dashboard/BreakAllowancePanel.vue';
import UnidentifiedAlertPanel from '@/components/dashboard/UnidentifiedAlertPanel.vue';
import ManualCorrectionPanel from '@/components/dashboard/ManualCorrectionPanel.vue';

const refreshInterval = ref('5');
const { cameras, stats, isConnected, isStreaming } = useDetectionStream();

const router = useRouter();

// Sisa demo lama (membuka JSON mentah di tab baru) diganti tautan ke halaman terkait.
function handleExport() {
  router.push('/reports');
}

function handleConfigure() {
  router.push('/settings?tab=engine');
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
      <LiveFeedSection
        :cameras="cameras"
        :is-connected="isConnected"
        :is-streaming="isStreaming"
      />
      <BreakAllowancePanel />
      <UnidentifiedAlertPanel />
      <ManualCorrectionPanel ref="correctionPanelref" />
    </div>
  </DashboardLayout>
</template>
