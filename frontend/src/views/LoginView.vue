<script setup>
import { ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { LogIn, AlertCircle } from '@lucide/vue';
import { useAuth } from '@/composables/useAuth';

const route = useRoute();
const router = useRouter();
const { login } = useAuth();

const username = ref('');
const password = ref('');
const error = ref(null);
const isSubmitting = ref(false);

async function handleSubmit() {
  error.value = null;
  isSubmitting.value = true;
  try {
    await login(username.value, password.value);
    const target = typeof route.query.redirect === 'string' ? route.query.redirect : '/';
    router.replace(target.startsWith('/') ? target : '/');
  } catch (err) {
    error.value = err?.message || 'Login gagal';
  } finally {
    isSubmitting.value = false;
  }
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-slate-50 px-4">
    <form
      class="w-full max-w-sm space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-xs"
      @submit.prevent="handleSubmit"
    >
      <div>
        <h1 class="text-lg font-bold text-slate-900">Masuk</h1>
        <p class="text-xs text-slate-500">AI Time Tracking System</p>
      </div>

      <div>
        <label class="block text-xs font-semibold text-slate-700">Username</label>
        <input
          v-model="username"
          type="text"
          required
          autocomplete="username"
          class="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-hidden focus:ring-1 focus:ring-indigo-500"
        />
      </div>

      <div>
        <label class="block text-xs font-semibold text-slate-700">Password</label>
        <input
          v-model="password"
          type="password"
          required
          autocomplete="current-password"
          class="mt-1.5 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:border-indigo-500 focus:outline-hidden focus:ring-1 focus:ring-indigo-500"
        />
      </div>

      <div v-if="error" class="flex items-start gap-2 rounded-lg bg-red-50 p-3 text-xs text-red-700">
        <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
        <span>{{ error }}</span>
      </div>

      <button
        type="submit"
        :disabled="isSubmitting"
        class="flex w-full items-center justify-center gap-2 rounded-lg bg-slate-900 px-4 py-2.5 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-40"
      >
        <LogIn class="h-3.5 w-3.5" />
        <span>{{ isSubmitting ? 'Memeriksa...' : 'Masuk' }}</span>
      </button>
    </form>
  </div>
</template>
