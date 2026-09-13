<script setup>
import { Bell, Building2, FileText, History, LayoutDashboard, Settings, ShieldCheck, Users, Video } from '@lucide/vue';
import { RouterLink, useRoute } from 'vue-router';
import { Badge } from '../ui/badge';

const route = useRoute();

const mainNav = [
  { label: 'Dashboard', icon: LayoutDashboard, to: '/' },
  { label: 'Live Monitoring', icon: Video, to: '/live-monitoring' },
  { label: 'Usage History', icon: History, to: '/usage-history' },
  { label: 'Facilities', icon: Building2, to: '/facilities' },
  { label: 'Employees', icon: Users, to: '/employees' },
  { label: 'Reports', icon: FileText, to: '/reports' },
  { label: 'Notifications', icon: Bell, to: '/notifications', badge: 3 },
];

const systemNav = [
    { label: 'Settings', icon: Settings, to: '/settings' },
]

const isActive = (path) => route.path === path
</script>

<template>
    <aside class="flex h-screen w-64 flex-col border-r bg-white">
        <div class="flex items-center gap-2 px-5 py-5">
            <div class="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-900">
                <ShieldCheck class="h-5 w-5 text-white" />
            </div>
            <div class="leading-tight">
                <p class="text-sm font-semibold text-slate-900">Facility Monitor</p>
                <p class="text-xs text-slate-500">CV Surveillance Telemetry</p>
            </div>
        </div>
        <nav class="flex-1 space-y-1 px-3 pt-2">
            <RouterLink
                v-for="item in mainNav"
                :key="item.label"
                :to="item.to"
                class="flex items-center justify-between rounded-lg px-3 py-2 text-sm font-medium transition-colors"
                :class="isActive(item.to)
                ? 'bg-indigo-50 text-indigo-600'
                : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'"
            >
                <span class="flex items-center gap-3">
                    <component :is="item.icon" class="h-4 w-4" />
                    {{ item.label }}
                </span>
                <Badge v-if="item.badge" variant="secondary" class="h-5 px-1.5 text-xs">
                    {{ item.badge }}
                </Badge>
            </RouterLink>

            <p class="px-3 pb-1 pt-5 text-xs font-semibold uppercase tracking-wider text-slate-400">
                System
            </p>
            <RouterLink
                v-for="item in systemNav"
                :key="item.label"
                :to="item.to"
                class="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-50 hover:text-slate-900"
                :class="isActive(item.to) && 'bg-indigo-50 text-indigo-600'"
            >
                <component :is="item.icon" class="h-4 w-4" />
                {{ item.label }}
            </RouterLink>
        </nav>

        <div class="flex items-center gap-3 border-t px-4 py-4">
            <div class="flex h-9 w-9 items-center justify-center rounded-full bg-indigo-100 text-sm font-semibold text-indigo-600">
                AD
            </div>
            <div class="min-w-0 flex-1 leading-tight">
                <p class="truncate text-sm font-medium text-slate-900">Administrator</p>
                <p class="truncate text-xs text-slate-500">admin@company.com</p>
            </div>
            <ChevronsUpDown class="h-4 w-4 shrink-0 text-slate-400" />
        </div>
    </aside>
</template>
