<script setup>
import { ref } from 'vue';
import DashboardLayout from '@/layouts/DashboardLayout.vue';
import DashboardHeader from '@/components/dashboard/DashboardHeader.vue';
import PipelineSteps from '@/components/dashboard/PipelineSteps.vue';
import StatsRow from '@/components/dashboard/StatsRow.vue';
import LiveFeedSection from '@/components/dashboard/LiveFeedSection.vue';

const refreshInterval = ref('5');

function handleExport() {
  console.log('export report');
}
function handleConfigure() {
  console.log('open configure facilities');
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
      <!-- <PipelineSteps />
      <StatsRow /> -->
      <LiveFeedSection />
    </div>
  </DashboardLayout>
</template>
