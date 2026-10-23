// Isolated browser fixture; exercises production scene preparation components.
import { createApp, h } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import SceneWorkspace from '../src/components/SceneWorkspace.vue'
import '../src/styles.css'
import '../src/styles/tokens.css'
import '../src/styles/base.css'
import '../src/styles/components.css'
import '../src/styles/responsive.css'
import '../src/styles/readability.css'
import type { Community } from '../src/domain/models'
const community:Community={id:'scenario-layout',name:'安巷社区 · 案例配置',address:'示例路18号',description:null,status:'draft',created_at:'2026-10-21',updated_at:'2026-10-21',owner_username:'layout',versions:[]}
const router=createRouter({history:createWebHistory(),routes:[{path:'/tests/scenario-preparation.html',name:'scenes',component:{render:()=>null}},{path:'/projects',name:'projects',component:{render:()=>null}},{path:'/map',name:'map',component:{render:()=>null}},{path:'/operations',name:'operations',component:{render:()=>null}}]})
const app=createApp({render:()=>h(SceneWorkspace,{apiBaseUrl:'/__scenario_layout__',accessToken:'fixture',community})})
app.use(router)
await router.isReady()
app.mount('#app')
