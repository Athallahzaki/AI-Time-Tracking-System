<script setup>
import { RouterLink } from 'vue-router';
import DashboardLayout from '@/layouts/DashboardLayout.vue';
import EnrollmentPanel from '@/components/dashboard/EnrollmentPanel.vue';
import { ShieldCheck, ArrowLeft, Lightbulb } from '@lucide/vue';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
</script>

<template>
  <DashboardLayout :crumbs="['Karyawan', 'Pendaftaran Wajah']">
    <div class="space-y-5 max-w-7xl mx-auto">
      <!-- Page Header -->
      <div
        class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-b border-slate-200/80 pb-4"
      >
        <div>
          <div class="flex items-center gap-2">
            <h1 class="text-xl font-bold tracking-tight text-slate-900">
              Pendaftaran Wajah Karyawan
            </h1>
            <Badge
              variant="secondary"
              class="bg-indigo-50 font-semibold text-indigo-700"
            >
              <ShieldCheck />
              Sistem AI Rekognisi
            </Badge>
          </div>
          <p class="mt-1 text-xs text-slate-500">
            Daftarkan identitas dan foto referensi karyawan untuk pelacakan
            kehadiran otomatis via AI Vision Engine.
          </p>
        </div>

        <div class="flex items-center gap-2">
          <Button
            as-child
            variant="outline"
            size="sm"
            class="h-8 text-xs text-slate-700"
          >
            <RouterLink to="/">
              <ArrowLeft />
              Kembali ke Dashboard
            </RouterLink>
          </Button>
        </div>
      </div>

      <!-- Panduan / Tips Box -->
      <div
        class="rounded-xl border border-indigo-100 bg-linear-to-r from-indigo-50/70 via-sky-50/50 to-white p-4"
      >
        <div class="flex items-start gap-3">
          <div
            class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-600 text-white shadow-xs"
          >
            <Lightbulb class="h-4 w-4" />
          </div>
          <div class="space-y-1">
            <h3
              class="text-xs font-bold uppercase tracking-wider text-indigo-900"
            >
              Pedoman Foto Referensi (Architecture §10)
            </h3>
            <ul class="grid gap-2 text-xs text-slate-600 sm:grid-cols-3 pt-1">
              <li class="flex items-start gap-1.5">
                <span class="font-bold text-indigo-600">•</span>
                <span
                  ><strong>Minimal 3 foto:</strong> Ambil foto dari beberapa
                  pose berbeda (lurus ke depan, sedikit miring kiri, dan miring
                  kanan).</span
                >
              </li>
              <li class="flex items-start gap-1.5">
                <span class="font-bold text-indigo-600">•</span>
                <span
                  ><strong>Pencahayaan serupa CCTV:</strong> Gunakan pencahayaan
                  normal ruangan kantor dan hindari bayangan gelap ekstrem atau
                  backlight.</span
                >
              </li>
              <li class="flex items-start gap-1.5">
                <span class="font-bold text-indigo-600">•</span>
                <span
                  ><strong>Hindari Pas Foto Kaku:</strong> Model rekognisi
                  bekerja paling baik dengan foto alami yang menyerupai
                  tangkapan kamera nyata.</span
                >
              </li>
            </ul>
          </div>
        </div>
      </div>

      <!-- Main Enrollment Panel (Form + List) -->
      <EnrollmentPanel />
    </div>
  </DashboardLayout>
</template>
