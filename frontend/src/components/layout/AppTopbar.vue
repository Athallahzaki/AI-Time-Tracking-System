<script setup>
import { computed } from 'vue';
import { RouterLink, useRouter } from 'vue-router';
import { LayoutGrid, LogIn, LogOut, Menu } from '@lucide/vue';
import { useAuth } from '@/composables/useAuth';
import NotificationDropdown from './NotificationDropdown.vue';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Separator } from '@/components/ui/separator';

const router = useRouter();
const { isLoggedIn, user, logout } = useAuth();
const initials = computed(() =>
  (user.value?.username || '?').slice(0, 2).toUpperCase(),
);

async function handleLogout() {
  await logout();
  router.push('/login');
}

defineProps({
  crumbs: {
    type: Array,
    default: () => ['Dashboard', 'Overview'],
  },
});

defineEmits(['toggle-sidebar']);
</script>

<template>
  <header
    class="flex h-14 shrink-0 items-center justify-between border-b bg-white px-3 sm:px-6"
  >
    <!-- Kiri: tombol menu + breadcrumb -->
    <div class="flex min-w-0 items-center gap-2">
      <Button
        variant="ghost"
        size="icon-sm"
        class="-ml-1 text-slate-600 md:hidden"
        aria-label="Buka menu navigasi"
        @click="$emit('toggle-sidebar')"
      >
        <Menu class="size-5" />
      </Button>
      <Separator orientation="vertical" class="mr-1 h-4! md:hidden" />

      <LayoutGrid class="hidden h-4 w-4 shrink-0 text-slate-400 sm:block" />

      <!-- Mobile: hanya halaman aktif -->
      <span class="truncate text-xs font-medium text-slate-900 sm:hidden">
        {{ crumbs[crumbs.length - 1] }}
      </span>

      <!-- Desktop: jalur lengkap -->
      <Breadcrumb class="hidden sm:block">
        <BreadcrumbList class="gap-1.5 text-sm text-slate-500 sm:gap-1.5">
          <template v-for="(crumb, i) in crumbs" :key="crumb">
            <BreadcrumbItem>
              <BreadcrumbPage
                v-if="i === crumbs.length - 1"
                class="font-medium text-slate-900"
              >
                {{ crumb }}
              </BreadcrumbPage>
              <template v-else>{{ crumb }}</template>
            </BreadcrumbItem>
            <BreadcrumbSeparator
              v-if="i < crumbs.length - 1"
              class="text-slate-300"
            />
          </template>
        </BreadcrumbList>
      </Breadcrumb>
    </div>

    <!-- Kanan: notifikasi + akun -->
    <div class="flex shrink-0 items-center gap-1.5 sm:gap-2">
      <NotificationDropdown />

      <DropdownMenu v-if="isLoggedIn">
        <DropdownMenuTrigger as-child>
          <Button
            variant="ghost"
            size="icon-sm"
            class="rounded-full"
            :title="`${user?.username} (${user?.role})`"
            aria-label="Menu akun"
          >
            <Avatar class="size-7 sm:size-8">
              <AvatarFallback
                class="bg-indigo-100 text-xs font-semibold text-indigo-600"
              >
                {{ initials }}
              </AvatarFallback>
            </Avatar>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" class="w-56">
          <DropdownMenuLabel class="flex items-center justify-between gap-2">
            <span class="truncate">{{ user?.username }}</span>
            <Badge variant="secondary" class="capitalize">{{
              user?.role
            }}</Badge>
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem variant="destructive" @select="handleLogout">
            <LogOut />
            Keluar
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <Button v-else as-child variant="outline" size="sm" class="h-8 text-xs">
        <RouterLink to="/login">
          <LogIn />
          Masuk
        </RouterLink>
      </Button>
    </div>
  </header>
</template>
