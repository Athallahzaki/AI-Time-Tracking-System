<script setup>
import { computed, onMounted, ref } from 'vue';
import {
  ClipboardCheck,
  FileText,
  House,
  LayoutDashboard,
  Settings,
  ShieldCheck,
  UserCheck,
  Users,
} from '@lucide/vue';
import { RouterLink, useRoute } from 'vue-router';
import BrandMark from './BrandMark.vue';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';
import { useEnrollment } from '@/composables/useEnrollment';
import { useAuth } from '@/composables/useAuth';
import { countPendingReviews } from '@/api/reviews';
import { cn } from '@/lib/utils';

// Isi sidebar dipisah dari wadahnya: dipakai oleh <aside> desktop dan <Sheet> mobile.
defineEmits(['navigate']);

const route = useRoute();
const { enrolledPersons } = useEnrollment();
const { user, isAdmin } = useAuth();
const pendingReviews = ref(0);

onMounted(async () => {
  if (isAdmin.value) pendingReviews.value = await countPendingReviews();
});

// Menu disaring per peran. Admin = HR (semua menu); viewer = karyawan (dok. 12 §3.2).
const mainNav = computed(() => {
  if (!isAdmin.value) {
    return [{ label: 'Pemakaian Saya', icon: House, to: '/me' }];
  }
  return [
    { label: 'Dashboard', icon: LayoutDashboard, to: '/' },
    { label: 'Data Karyawan', icon: Users, to: '/employees' },
    {
      label: 'Enrollment Wajah',
      icon: UserCheck,
      to: '/enrollment',
      badge: enrolledPersons.length > 0 ? `${enrolledPersons.length}` : undefined,
    },
    { label: 'Report', icon: FileText, to: '/reports' },
    {
      label: 'Tinjauan HR',
      icon: ClipboardCheck,
      to: '/reviews',
      badge: pendingReviews.value > 0 ? `${pendingReviews.value}` : undefined,
      badgeClass: 'bg-amber-100 text-amber-800',
    },
    { label: 'Manajemen Pengguna', icon: ShieldCheck, to: '/users' },
    { label: 'Pengaturan Sistem', icon: Settings, to: '/settings' },
  ];
});

const isActive = (path) => {
  if (path === '/') return route.path === '/';
  return route.path === path || route.path.startsWith(`${path}/`);
};
</script>

<template>
  <div class="flex h-full flex-col">
    <div class="px-5 py-5">
      <BrandMark />
    </div>

    <nav class="flex-1 space-y-1 overflow-y-auto px-3">
      <Button
        v-for="item in mainNav"
        :key="item.label"
        as-child
        variant="ghost"
        :class="
          cn(
            'h-9 w-full justify-between px-3 font-medium',
            isActive(item.to)
              ? 'bg-indigo-50 text-indigo-600 hover:bg-indigo-50 hover:text-indigo-600'
              : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900',
          )
        "
      >
        <RouterLink :to="item.to" @click="$emit('navigate')">
          <span class="flex items-center gap-3">
            <component :is="item.icon" class="h-4 w-4" />
            {{ item.label }}
          </span>
          <Badge
            v-if="item.badge"
            variant="secondary"
            :class="cn('h-5 px-1.5', item.badgeClass || 'bg-indigo-100 text-indigo-700')"
          >
            {{ item.badge }}
          </Badge>
        </RouterLink>
      </Button>
    </nav>

    <Separator />

    <div class="flex items-center gap-3 px-4 py-3.5">
      <Avatar>
        <AvatarFallback
          class="bg-indigo-100 text-xs font-semibold text-indigo-600 uppercase"
        >
          {{ (user?.username || 'Guest').slice(0, 2) }}
        </AvatarFallback>
      </Avatar>
      <div class="min-w-0 flex-1 leading-tight">
        <p class="truncate text-sm font-medium text-slate-900">
          {{ user?.username || 'Tamu / Viewer' }}
        </p>
        <p class="truncate text-xs text-slate-500 capitalize">
          {{ user?.role === 'admin' ? 'Admin (HR)' : user ? 'Karyawan' : 'Belum masuk' }}
        </p>
      </div>
    </div>
  </div>
</template>
