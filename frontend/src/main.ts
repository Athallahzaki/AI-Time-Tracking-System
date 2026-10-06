import { createApp } from 'vue';
import './style.css';
import App from './App.vue';
import { createRouter, createWebHistory } from 'vue-router';
import DashboardView from './views/DashboardView.vue';
import EnrollmentView from './views/EnrollmentView.vue';
import LoginView from './views/LoginView.vue';
import { useAuth } from './composables/useAuth';

const routes = [
  { path: '/', component: DashboardView },
  { path: '/login', component: LoginView },
  // Enrollment mengubah data: backend menolak tanpa token admin (401).
  { path: '/enrollment', component: EnrollmentView, meta: { requiresAdmin: true } },
  { path: '/employees', redirect: '/enrollment' },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach((to) => {
  const { isAdmin } = useAuth();
  if (to.meta.requiresAdmin && !isAdmin.value) {
    return { path: '/login', query: { redirect: to.fullPath } };
  }
  return true;
});

createApp(App).use(router).mount('#app');
