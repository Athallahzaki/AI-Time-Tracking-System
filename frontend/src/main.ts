import { createApp } from 'vue';
import './style.css';
import App from './App.vue';
import { createRouter, createWebHistory } from 'vue-router';
import DashboardView from './views/DashboardView.vue';
import EnrollmentView from './views/EnrollmentView.vue';
import LoginView from './views/LoginView.vue';
import { useAuth } from './composables/useAuth';

import SettingsView from './views/SettingsView.vue';

const routes = [
  { path: '/', component: DashboardView },
  { path: '/login', component: LoginView },
  // Enrollment & Settings butuh peran admin.
  { path: '/enrollment', component: EnrollmentView, meta: { requiresAdmin: true } },
  { path: '/employees', redirect: '/enrollment' },
  { path: '/settings', component: SettingsView, meta: { requiresAdmin: true } },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach((to) => {
  const { isLoggedIn, isAdmin } = useAuth();

  // Jika belum login dan mencoba mengakses selain halaman login, redirect ke /login
  if (to.path !== '/login' && !isLoggedIn.value) {
    return { path: '/login', query: { redirect: to.fullPath } };
  }

  // Jika sudah login dan mencoba mengakses halaman /login, redirect ke dashboard
  if (to.path === '/login' && isLoggedIn.value) {
    return { path: '/' };
  }

  // Jika rute butuh role admin tetapi user bukan admin
  if (to.meta.requiresAdmin && !isAdmin.value) {
    return { path: '/' };
  }

  return true;
});

createApp(App).use(router).mount('#app');
