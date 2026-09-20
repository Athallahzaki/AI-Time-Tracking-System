<script setup>
defineProps({
  detection: { type: Object, required: true },
  compact: { type: Boolean, default: false },
});

const colorMap = {
  emerald:
    'border-emerald-400 text-emerald-300 shadow-[0_0_8px_rgba(52,211,153,0.3)]',
  amber:
    'border-amber-400 text-amber-300 shadow-[0_0_8px_rgba(251,191,36,0.3)]',
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
    <!-- Top label badge — ukuran teks dinaikkan (9/10px → 10/13px) untuk keterbacaan -->
    <div
      class="absolute left-0 z-10 whitespace-nowrap rounded font-semibold tracking-wide backdrop-blur-xs transition-colors"
      :class="[
        compact
          ? 'text-[10px] sm:text-[11px] px-1.5 py-0.5'
          : 'text-[11px] sm:text-[13px] px-1.5 sm:px-2 py-0.5 sm:py-1',
        parseFloat(detection.top) < 7 ? 'top-1' : '-top-6 sm:-top-7',
        detection.warning
          ? 'bg-red-500/90 text-white'
          : 'bg-slate-950/85 text-white border border-white/10',
      ]"
    >
      <span>{{ detection.label }}</span>
      <span v-if="detection.sub"> · {{ detection.sub }}</span>
      <span v-if="detection.conf"> · {{ detection.conf }}</span>
    </div>

    <!-- Bottom duration / extra badge — ikut dinaikkan agar konsisten dengan label atas -->
    <div
      v-if="detection.extra && !compact"
      class="absolute -bottom-6 sm:-bottom-7 left-0 z-10 whitespace-nowrap rounded px-1.5 sm:px-2 py-0.5 sm:py-1 text-[10px] sm:text-[11px] font-medium backdrop-blur-xs transition-colors"
      :class="
        detection.warning
          ? 'bg-red-500/90 text-white'
          : 'bg-slate-950/85 text-white border border-white/10'
      "
    >
      {{ detection.extra }}
    </div>

    <!-- HUD corner accents -->
    <span
      class="absolute -left-0.5 -top-0.5 h-1.5 w-1.5 border-l-2 border-t-2 border-white/80"
    ></span>
    <span
      class="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 border-r-2 border-t-2 border-white/80"
    ></span>
    <span
      class="absolute -bottom-0.5 -left-0.5 h-1.5 w-1.5 border-b-2 border-l-2 border-white/80"
    ></span>
    <span
      class="absolute -bottom-0.5 -right-0.5 h-1.5 w-1.5 border-b-2 border-r-2 border-white/80"
    ></span>
  </div>
</template>
