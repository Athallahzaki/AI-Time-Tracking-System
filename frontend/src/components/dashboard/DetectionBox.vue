<script setup>
defineProps({
  detection: { type: Object, required: true },
  compact: { type: Boolean, default: false },
});

const colorMap = {
  emerald: 'border-emerald-400 text-emerald-300 shadow-[0_0_8px_rgba(52,211,153,0.3)]',
  amber: 'border-amber-400 text-amber-300 shadow-[0_0_8px_rgba(251,191,36,0.3)]',
  red: 'border-red-400 text-red-300 shadow-[0_0_8px_rgba(248,113,113,0.4)]',
  cyan: 'border-cyan-400 text-cyan-300 shadow-[0_0_8px_rgba(34,211,238,0.3)]',
};
</script>

<template>
  <div
    class="pointer-events-none absolute rounded border-2 transition-all duration-75 ease-linear"
    :class="colorMap[detection.color] || colorMap.emerald"
    :style="{
      top: detection.top,
      left: detection.left,
      width: detection.width,
      height: detection.height,
    }"
  >
    <!-- Top label badge -->
    <div
      class="absolute left-0 z-10 whitespace-nowrap rounded font-semibold tracking-wide backdrop-blur-xs transition-colors"
      :class="[
        compact ? 'text-[8px] sm:text-[9px] px-1 py-0' : 'text-[8px] sm:text-[10px] px-1 sm:px-1.5 py-0.5',
        parseFloat(detection.top) < 7 ? 'top-1' : '-top-5 sm:-top-6',
        detection.warning
          ? 'bg-red-500/90 text-white'
          : 'bg-slate-950/85 text-white border border-white/10',
      ]"
    >
      <span>{{ detection.label }}</span>
      <span v-if="detection.sub"> · {{ detection.sub }}</span>
      <span v-if="detection.conf"> · {{ detection.conf }}</span>
    </div>

    <!-- Bottom duration / extra badge (shown when extra exists, or hidden in very compact view if no room) -->
    <div
      v-if="detection.extra && !compact"
      class="absolute -bottom-5 sm:-bottom-6 left-0 z-10 whitespace-nowrap rounded px-1 sm:px-1.5 py-0.5 text-[8px] sm:text-[10px] font-medium backdrop-blur-xs transition-colors"
      :class="
        detection.warning
          ? 'bg-red-500/90 text-white'
          : 'bg-slate-950/85 text-white border border-white/10'
      "
    >
      {{ detection.extra }}
    </div>

    <!-- HUD corner accents -->
    <span class="absolute -left-0.5 -top-0.5 h-1.5 w-1.5 border-l-2 border-t-2 border-white/80"></span>
    <span class="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 border-r-2 border-t-2 border-white/80"></span>
    <span class="absolute -bottom-0.5 -left-0.5 h-1.5 w-1.5 border-b-2 border-l-2 border-white/80"></span>
    <span class="absolute -bottom-0.5 -right-0.5 h-1.5 w-1.5 border-b-2 border-r-2 border-white/80"></span>
  </div>
</template>
