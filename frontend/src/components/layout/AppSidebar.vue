<script setup>
import { watch } from 'vue';
import { useMediaQuery } from '@vueuse/core';
import AppSidebarContent from './AppSidebarContent.vue';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from '@/components/ui/sheet';

const props = defineProps({
  isOpen: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits(['close']);

// Drawer mobile ditutup otomatis bila layar melebar ke breakpoint md,
// supaya overlay Sheet tidak tertinggal di tampilan desktop.
const isDesktop = useMediaQuery('(min-width: 768px)');
watch(isDesktop, (desktop) => {
  if (desktop && props.isOpen) emit('close');
});

function onOpenChange(open) {
  if (!open) emit('close');
}
</script>

<template>
  <!-- Desktop: sidebar statis -->
  <aside class="hidden h-screen w-64 shrink-0 border-r bg-white md:block">
    <AppSidebarContent />
  </aside>

  <!-- Mobile: drawer shadcn Sheet -->
  <Sheet :open="isOpen" @update:open="onOpenChange">
    <SheetContent side="left" class="w-64 gap-0 bg-white p-0 sm:max-w-64">
      <SheetTitle class="sr-only">Navigasi</SheetTitle>
      <SheetDescription class="sr-only"
        >Menu navigasi utama dashboard</SheetDescription
      >
      <AppSidebarContent @navigate="emit('close')" />
    </SheetContent>
  </Sheet>
</template>
