<script setup>
import { Download, Settings2 } from '@lucide/vue';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

defineProps({
  refreshInterval: {
    type: String,
    default: '5',
  },
});

const emit = defineEmits(['update:refreshInterval', 'export', 'configure']);
</script>

<template>
  <div class="flex flex-col gap-3.5 sm:flex-row sm:items-start sm:justify-between">
    <div>
      <h1 class="text-xl sm:text-2xl font-semibold text-slate-900 tracking-tight">
        Monitoring Dashboard
      </h1>
      <p class="mt-0.5 sm:mt-1 text-xs sm:text-sm text-slate-500">
        Monitor employee entertainment facility usage and Computer Vision
        activity in real time.
      </p>
    </div>

    <!-- <div class="flex items-center gap-2 sm:gap-3 w-full sm:w-auto">
      <Button
        variant="outline"
        class="flex-1 sm:flex-initial justify-center gap-1.5 sm:gap-2 text-xs sm:text-sm h-8.5 sm:h-9 px-3"
        @click="emit('export')"
      >
        <Download class="h-3.5 w-3.5 sm:h-4 sm:w-4" />
        Export Report
      </Button>

      <Button
        class="flex-1 sm:flex-initial justify-center gap-1.5 sm:gap-2 text-xs sm:text-sm h-8.5 sm:h-9 px-3 bg-slate-900 hover:bg-slate-800"
        @click="emit('configure')"
      >
        <Settings2 class="h-3.5 w-3.5 sm:h-4 sm:w-4" />
        Configure Facilities
      </Button>
    </div> -->
  </div>
</template>
