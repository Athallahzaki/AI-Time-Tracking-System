import { createApp } from 'vue';
import './style.css';
import App from './App.vue';
import { createRouter, createWebHistory } from 'vue-router';
import DashboardView from './views/DashboardView.vue';
import EnrollmentView from './views/EnrollmentView.vue';

const routes = [
  { path: '/', component: DashboardView },
  { path: '/enrollment', component: EnrollmentView },
  { path: '/employees', redirect: '/enrollment' },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

createApp(App).use(router).mount('#app');
