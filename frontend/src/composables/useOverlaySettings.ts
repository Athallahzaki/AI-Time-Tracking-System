import { ref } from 'vue';

const STORAGE_KEY = 'ai-time.overlay.identity-status';

function loadPreference(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== 'off';
  } catch {
    return true;
  }
}

const showIdentityStatus = ref(loadPreference());

function toggleIdentityStatus() {
  showIdentityStatus.value = !showIdentityStatus.value;

  try {
    localStorage.setItem(
      STORAGE_KEY,
      showIdentityStatus.value ? 'on' : 'off',
    );
  } catch {
    // Preferensi tetap berlaku selama halaman terbuka.
  }
}

export function useOverlaySettings() {
  return {
    showIdentityStatus,
    toggleIdentityStatus,
  };
}