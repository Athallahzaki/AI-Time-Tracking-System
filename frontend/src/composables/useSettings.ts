import { ref } from 'vue';
import { apiFetch } from './useAuth';

export interface BreakPolicyConfig {
  daily_free_time_allowance_minutes: number;
  warning_remaining_minutes: number;
  qualification_seconds: number;
  official_breaks: Array<{ start: string; end: string }>;
  visit_merge_gap_seconds: number;
  open_presence_stale_seconds: number;
  timezone: string;
}

export interface EmailStatus {
  enabled: boolean;
  configured: boolean;
  host: string;
  port: number;
  security: string;
  from: string | null;
  recipients: string[];
  username_configured: boolean;
  password_configured: boolean;
  worker_running: boolean;
}

export function useSettings() {
  const policy = ref<BreakPolicyConfig | null>(null);
  const emailStatus = ref<EmailStatus | null>(null);
  const isLoading = ref<boolean>(false);
  const isSaving = ref<boolean>(false);
  const isSendingTestEmail = ref<boolean>(false);
  const error = ref<string | null>(null);
  const successMessage = ref<string | null>(null);

  async function fetchPolicy(): Promise<void> {
    isLoading.value = true;
    error.value = null;
    try {
      const res = await apiFetch('/api/settings/policy');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      policy.value = data.policy;
    } catch (err: any) {
      error.value = err.message || 'Gagal memuat pengaturan kebijakan';
    } finally {
      isLoading.value = false;
    }
  }

  async function updatePolicy(
    dailyAllowanceMinutes: number,
    warningRemainingMinutes: number
  ): Promise<boolean> {
    isSaving.value = true;
    error.value = null;
    successMessage.value = null;
    try {
      const res = await apiFetch('/api/settings/policy', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          daily_free_time_allowance_minutes: dailyAllowanceMinutes,
          warning_remaining_minutes: warningRemainingMinutes,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      policy.value = data.policy;
      successMessage.value = 'Kebijakan berhasil diperbarui!';
      return true;
    } catch (err: any) {
      error.value = err.message || 'Gagal menyimpan kebijakan';
      return false;
    } finally {
      isSaving.value = false;
    }
  }

  async function fetchEmailStatus(): Promise<void> {
    try {
      const res = await apiFetch('/api/settings/email');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      emailStatus.value = data.email;
    } catch (err: any) {
      console.error('Gagal mengambil status email:', err);
    }
  }

  async function sendTestEmail(): Promise<{ success: boolean; message: string }> {
    isSendingTestEmail.value = true;
    try {
      const res = await apiFetch('/api/settings/email/test', {
        method: 'POST',
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || `Gagal mengirim email (${res.status})`);
      }
      return {
        success: true,
        message: data.message || 'Email uji coba berhasil dikirim!',
      };
    } catch (err: any) {
      return {
        success: false,
        message: err.message || 'Gagal mengirim email uji coba',
      };
    } finally {
      isSendingTestEmail.value = false;
    }
  }

  return {
    policy,
    emailStatus,
    isLoading,
    isSaving,
    isSendingTestEmail,
    error,
    successMessage,
    fetchPolicy,
    updatePolicy,
    fetchEmailStatus,
    sendTestEmail,
  };
}
