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
  <div class="flex items-start justify-between">
    <div>
      <h1 class="text-2xl font-semibold text-slate-900">
        Monitoring Dashboard
      </h1>
      <p class="mt-1 text-sm text-slate-500">
        Monitor employee entertainment facility usage and Computer Vision
        activity in real time.
      </p>
    </div>

    <div class="flex items-center gap-3">
      <!-- <div
        class="flex items-center gap-2 rounded-lg border bg-white px-3 py-1.5"
      >
        <span class="flex items-center gap-1.5 text-sm text-slate-600">
          <span class="h-1.5 w-1.5 rounded-full bg-green-500"></span>
          Live Feed:
        </span>
        <Select
          :model-value="refreshInterval"
          @update:model-value="(v) => emit('update:refreshInterval', v)"
        >
          <SelectTrigger
            class="h-7 w-37.5 border-none px-1 text-sm font-medium shadow-none focus:ring-0"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="5">Auto-refresh (5s)</SelectItem>
            <SelectItem value="10">Auto-refresh (10s)</SelectItem>
            <SelectItem value="30">Auto-refresh (30s)</SelectItem>
            <SelectItem value="off">Off</SelectItem>
          </SelectContent>
        </Select>
      </div> -->

      <Button variant="outline" class="gap-2" @click="emit('export')">
        <Download class="h-4 w-4" />
        Export Report
      </Button>

      <Button
        class="gap-2 bg-slate-900 hover:bg-slate-800"
        @click="emit('configure')"
      >
        <Settings2 class="h-4 w-4" />
        Configure Facilities
      </Button>
    </div>
  </div>
</template>
