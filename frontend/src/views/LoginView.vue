<script setup>
import { ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { AlertCircle, Eye, EyeOff, Loader2, ShieldCheck } from '@lucide/vue';
import { useAuth } from '@/composables/useAuth';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

const route = useRoute();
const router = useRouter();
const { login } = useAuth();

const username = ref('');
const password = ref('');
const showPassword = ref(false);
const error = ref(null);
const isSubmitting = ref(false);

async function handleSubmit() {
  error.value = null;
  isSubmitting.value = true;
  try {
    await login(username.value.trim(), password.value);
    const target =
      typeof route.query.redirect === 'string' ? route.query.redirect : '/';
    router.replace(target.startsWith('/') ? target : '/');
  } catch (err) {
    error.value = err?.message || 'Login gagal';
  } finally {
    isSubmitting.value = false;
  }
}
</script>

<template>
  <div
    class="flex min-h-svh flex-col items-center justify-center bg-slate-50 px-4 py-10"
  >
    <div class="w-full max-w-sm">
      <!-- Brand: sama dengan header sidebar -->
      <div class="mb-6 flex flex-col items-center gap-3 text-center">
        <div
          class="flex h-11 w-11 items-center justify-center rounded-xl bg-slate-900 text-white shadow-xs"
        >
          <ShieldCheck class="h-6 w-6" />
        </div>
        <div class="leading-tight">
          <p class="text-base font-semibold text-slate-900">Hotel Murah</p>
          <p class="text-xs text-slate-500">AI Time Tracking System</p>
        </div>
      </div>

      <Card class="gap-6 shadow-xs">
        <CardHeader class="text-center">
          <CardTitle class="text-lg">Masuk</CardTitle>
          <CardDescription
            >Masukkan username dan password akun Anda.</CardDescription
          >
        </CardHeader>

        <CardContent>
          <form class="space-y-4" @submit.prevent="handleSubmit">
            <Alert
              v-if="error"
              variant="destructive"
              class="border-red-200 bg-red-50"
            >
              <AlertCircle />
              <AlertDescription>{{ error }}</AlertDescription>
            </Alert>

            <div class="space-y-2">
              <Label for="username">Username</Label>
              <Input
                id="username"
                v-model="username"
                type="text"
                required
                autofocus
                autocomplete="username"
                placeholder="admin"
                :aria-invalid="!!error || undefined"
              />
            </div>

            <div class="space-y-2">
              <Label for="password">Password</Label>
              <div class="relative">
                <Input
                  id="password"
                  v-model="password"
                  :type="showPassword ? 'text' : 'password'"
                  required
                  autocomplete="current-password"
                  placeholder="••••••••"
                  class="pr-10"
                  :aria-invalid="!!error || undefined"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  class="absolute top-1/2 right-0.5 -translate-y-1/2 text-slate-400 hover:bg-transparent hover:text-slate-700"
                  :aria-label="
                    showPassword ? 'Sembunyikan password' : 'Tampilkan password'
                  "
                  @click="showPassword = !showPassword"
                >
                  <EyeOff v-if="showPassword" />
                  <Eye v-else />
                </Button>
              </div>
            </div>

            <Button type="submit" class="w-full" :disabled="isSubmitting">
              <Loader2 v-if="isSubmitting" class="animate-spin" />
              {{ isSubmitting ? 'Memeriksa...' : 'Masuk' }}
            </Button>
          </form>
        </CardContent>
      </Card>

      <p class="mt-6 text-center text-xs text-slate-400">
        Lupa password? Hubungi administrator sistem.
      </p>
    </div>
  </div>
</template>
