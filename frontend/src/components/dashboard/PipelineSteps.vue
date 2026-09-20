<script setup>
import {
  Video,
  BrainCircuit,
  UserCheck,
  Activity,
  Hash,
  Timer,
  ShieldCheck,
  ChevronRight,
} from '@lucide/vue';

const steps = [
  { label: 'CCTV Stream', icon: Video },
  { label: 'CV Inference', icon: BrainCircuit },
  { label: 'Person Detect', icon: UserCheck },
  { label: 'Activity Detect', icon: Activity },
  { label: 'Tracking ID', icon: Hash },
  { label: 'Session Timer', icon: Timer },
  { label: 'Limit Check', icon: ShieldCheck },
];
</script>

<template>
  <div
    class="flex flex-wrap items-center gap-2 rounded-xl border bg-white px-4 py-3"
  >
    <template v-for="(step, i) in steps" :key="step.label">
      <div
        class="flex items-center gap-1.5 rounded-md bg-slate-50 px-2.5 py-1.5 text-xs font-medium text-slate-600"
      >
        <component :is="step.icon" class="h-3.5 w-3.5 text-slate-400" />
        {{ step.label }}
      </div>
      <ChevronRight
        v-if="i < steps.length - 1"
        class="h-3.5 w-3.5 shrink-0 text-slate-300"
      />
    </template>
  </div>
</template>
