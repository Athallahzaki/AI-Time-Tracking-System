<script setup>
defineProps({
  // salah satu dari GapClassification: tracking_loss | break | departure |
  // camera_failure | system_event | official_break | unknown
  classification: { type: String, required: true },
});

const LABELS = {
  tracking_loss: 'Kegagalan Tracking',
  break: 'Istirahat',
  departure: 'Pulang',
  camera_failure: 'Kamera Mati',
  system_event: 'Event Sistem',
  official_break: 'Jam Istirahat Resmi',
  unknown: 'Perlu Ditinjau',
};

const STYLES = {
  tracking_loss: 'border-dashed border-amber-300 bg-amber-50 text-amber-700',
  break: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  departure: 'border-slate-200 bg-slate-100 text-slate-600',
  camera_failure: 'border-orange-200 bg-orange-50 text-orange-700',
  system_event: 'border-dashed border-slate-300 bg-slate-50 text-slate-500',
  official_break: 'border-sky-200 bg-sky-50 text-sky-700',
  unknown: 'border-red-200 bg-red-50 text-red-700',
};

const DOTS = {
  tracking_loss: 'bg-amber-500',
  break: 'bg-emerald-500',
  departure: 'bg-slate-400',
  camera_failure: 'bg-orange-500',
  system_event: 'bg-slate-400',
  official_break: 'bg-sky-500',
  unknown: 'bg-red-500',
};
</script>

<template>
  <span
    class="inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium"
    :class="STYLES[classification] || STYLES.unknown"
  >
    <span
      class="h-1.5 w-1.5 rounded-full"
      :class="DOTS[classification] || DOTS.unknown"
    />
    {{ LABELS[classification] || classification }}
  </span>
</template>
