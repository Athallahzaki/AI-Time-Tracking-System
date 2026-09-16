<script setup>
import { Building2, Clock, Users, Gauge, AlertTriangle } from '@lucide/vue';
import StatCard from './StatCard.vue';

defineProps({
  stats: {
    type: Object,
    default: () => ({
      activeFacilities: 3,
      totalFacilities: 8,
      activeUsers: 7,
      totalUsage: '4h 32m',
      avgSession: '38 min',
      exceededDuration: 2,
    }),
  },
});
</script>

<template>
  <div class="grid grid-cols-2 gap-2.5 sm:grid-cols-2 lg:grid-cols-5 sm:gap-4">
    <StatCard
      :icon="Building2"
      icon-bg="bg-indigo-50"
      icon-color="text-indigo-500"
      label="Active Facilities"
      :value="stats.activeFacilities"
      :suffix="`/ ${stats.totalFacilities}`"
      :footnote="`Currently in use (${Math.round((stats.activeFacilities / stats.totalFacilities) * 100)}%)`"
    />

    <StatCard
      :icon="Users"
      icon-bg="bg-blue-50"
      icon-color="text-blue-500"
      label="Active Users"
      :value="stats.activeUsers"
      badge="+2 vs last hr"
      footnote="Employees detected right now"
    />

    <StatCard
      :icon="Clock"
      icon-bg="bg-amber-50"
      icon-color="text-amber-500"
      label="Today's Total Usage"
      :value="stats.totalUsage"
      footnote="Aggregated across 8 facilities"
    />

    <StatCard
      :icon="Gauge"
      icon-bg="bg-emerald-50"
      icon-color="text-emerald-500"
      label="Average Session"
      :value="stats.avgSession"
      footnote="Target limit: 45-60 min"
    />

    <StatCard
      :icon="AlertTriangle"
      icon-bg="bg-red-100"
      icon-color="text-red-500"
      label="Exceeded Duration"
      :value="stats.exceededDuration"
      footnote="Action Required"
      footnote-color="text-red-500"
      variant="warning"
      class="col-span-2 sm:col-span-1 lg:col-span-1"
    />
  </div>
</template>
