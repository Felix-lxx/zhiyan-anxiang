import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const RouteAnchor = { render: () => null }

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/projects' },
  { path: '/login', name: 'login', component: RouteAnchor, meta: { public: true, title: '登录' } },
  { path: '/projects', name: 'projects', component: () => import('./components/ProjectHome.vue'), meta: { title: '社区项目' } },
  { path: '/communities/:communityId/map', name: 'map', component: () => import('./components/MapEditor.vue'), meta: { title: '社区地图' } },
  { path: '/communities/:communityId/scenes', name: 'scenes', component: () => import('./components/SceneWorkspace.vue'), meta: { title: '演练场景' } },
  { path: '/communities/:communityId/operations', name: 'operations', component: () => import('./components/OperationsCenter.vue'), meta: { title: '三维导演台' } },
  { path: '/communities/:communityId/participant', name: 'participant-local', component: () => import('./components/ParticipantConsole.vue'), meta: { title: '参演端' } },
  { path: '/participant/:drillId', name: 'participant-invite', component: () => import('./components/ParticipantConsole.vue'), meta: { public: true, title: '手机参演端' } },
  { path: '/:pathMatch(.*)*', redirect: '/projects' },
]

export const router = createRouter({ history: createWebHistory(), routes })
// App.vue waits for HttpOnly session restoration before guarding protected routes.

router.afterEach((to) => {
  document.title = `${String(to.meta.title ?? '工作台')} · 智演安巷`
})
