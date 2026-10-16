import { createApp } from 'vue';
import './style.css';
import App from './App.vue';
import { createRouter, createWebHistory } from 'vue-router';
import DashboardView from './views/DashboardView.vue';
import EnrollmentView from './views/EnrollmentView.vue';
import LoginView from './views/LoginView.vue';
import { homePathFor, useAuth } from './composables/useAuth';

import SettingsView from './views/SettingsView.vue';

// Halaman baru dimuat saat dibutuhkan supaya bundle awal (dashboard) tetap kecil.
const EmployeesView = () => import('./views/EmployeesView.vue');
const UsersView = () => import('./views/UsersView.vue');
const ReportsView = () => import('./views/ReportsView.vue');
const ReviewQueueView = () => import('./views/ReviewQueueView.vue');
const ViewerHomeView = () => import('./views/ViewerHomeView.vue');
const ChangePasswordView = () => import('./views/ChangePasswordView.vue');

// meta.roles: peran yang boleh membuka halaman. Ini hanya kenyamanan UI —
// penyaringan sebenarnya WAJIB di backend (dok. 12 §3.8).
const ADMIN = { roles: ['admin'] };
const VIEWER = { roles: ['viewer'] };

const routes = [
  { path: '/', component: DashboardView, meta: ADMIN },
  { path: '/login', component: LoginView },
  { path: '/me', component: ViewerHomeView, meta: VIEWER },
  { path: '/change-password', component: ChangePasswordView },
  { path: '/employees', component: EmployeesView, meta: ADMIN },
  { path: '/users', component: UsersView, meta: ADMIN },
  { path: '/enrollment', component: EnrollmentView, meta: ADMIN },
  { path: '/reports', component: ReportsView, meta: ADMIN },
  { path: '/reviews', component: ReviewQueueView, meta: ADMIN },
  { path: '/settings', component: SettingsView, meta: ADMIN },
  { path: '/:pathMatch(.*)*', redirect: '/' },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach((to) => {
  const { isLoggedIn, user, mustChangePassword } = useAuth();

  // Belum login → /login (kecuali sudah di sana).
  if (to.path !== '/login' && !isLoggedIn.value) {
    return { path: '/login', query: { redirect: to.fullPath } };
  }

  // Sudah login tapi membuka /login → beranda sesuai peran.
  if (to.path === '/login' && isLoggedIn.value) {
    return { path: homePathFor(user.value) };
  }

  // Login pertama dengan password sementara → wajib ganti dulu.
  if (isLoggedIn.value && mustChangePassword.value && to.path !== '/change-password') {
    return { path: '/change-password' };
  }

  const roles = (to.meta as { roles?: string[] }).roles;
  if (roles && user.value) {
    const role = user.value.role === 'admin' ? 'admin' : 'viewer';
    if (!roles.includes(role)) return { path: homePathFor(user.value) };
  }

  return true;
});

// Sinkronkan profil (employee_id, must_change_password) bila sesi lama masih tersimpan.
useAuth().refreshMe();

createApp(App).use(router).mount('#app');
