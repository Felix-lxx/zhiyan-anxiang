<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
import AppIcon from './AppIcon.vue'
import { ApiError, createApiClient } from '../api/client'
import CommunityReadiness from './CommunityReadiness.vue'
import type { Community } from '../domain/models'

const props = defineProps<{
  apiBaseUrl: string
  accessToken: string
  username: string
  role: string
}>()

const emit = defineEmits<{ logout: []; openMap: [community: Community]; openOperations: [community: Community] }>()
const api = createApiClient(props.apiBaseUrl, () => props.accessToken, () => emit('logout'))
const route = useRoute()
const router = useRouter()
type HomeSection = 'projects' | 'training' | 'guide' | 'account'
const sectionNames: Record<HomeSection, string> = { projects: '社区项目', training: '示例训练', guide: '使用说明', account: '个人中心' }

const communities = ref<Community[]>([])
const isLoading = ref(true)
const isCreating = ref(false)
const isCreatingDemo = ref(false)
const isLaunchingThreeDemo = ref(false)
const isCreateFormOpen = ref(false)
const editing = ref<Community|null>(null), inspectingId = ref(''), savedNotice=ref(''), conflict=ref(false)
const baseline=ref('')
const dirty=computed(()=>isCreateFormOpen.value && JSON.stringify(form.value)!==baseline.value)
function allowLeave(){return !isCreating.value && (!dirty.value || window.confirm('社区资料尚未保存，确定放弃修改？'))}
function beforeUnload(event:BeforeUnloadEvent){if(dirty.value)event.preventDefault()}
onBeforeRouteLeave(allowLeave)
onBeforeRouteUpdate((to,from)=>to.query.section===from.query.section || allowLeave())
onBeforeUnmount(()=>window.removeEventListener('beforeunload',beforeUnload))
const listError = ref('')
const createError = ref('')
const demoError = ref('')
const search = ref('')
const statusFilter = ref('all')
const statusNames: Record<Community['status'], string> = { draft: '草稿', published: '已发布', archived: '已归档' }
const filteredCommunities = computed(() => communities.value.filter(item =>
  (statusFilter.value === 'all' || item.status === statusFilter.value) &&
  [item.name, item.address ?? '', item.description ?? ''].join(' ').toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase())
).sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)))
function latestVersion(community: Community): string {
  return [...community.versions].sort((a, b) => b.version_number - a.version_number)[0]?.name ?? '待生成版本'
}
function resetFilters(): void { search.value = ''; statusFilter.value = 'all' }
const activeSection = computed<HomeSection>(() => {
  const section = typeof route.query.section === 'string' ? route.query.section : 'projects'
  return ['projects', 'training', 'guide', 'account'].includes(section) ? section as HomeSection : 'projects'
})
const activeSectionName = computed(() => sectionNames[activeSection.value])
async function openSection(section: HomeSection): Promise<void> {
  if (!allowLeave()) return
  isCreateFormOpen.value = false
  createError.value = ''
  form.value = { name: '', address: '', description: '' }
  await router.push(section === 'projects' ? { name: 'projects' } : { name: 'projects', query: { section } })
  await nextTick()
  document.getElementById(`${section}-view-title`)?.focus({ preventScroll: true })
  window.scrollTo({ top: 0, behavior: 'auto' })
}
const form = ref({ name: '', address: '', description: '' })

const projectCountLabel = computed(() => `${communities.value.length} 个社区项目`)
const roleLabel = computed(() => props.role === 'admin' ? '系统管理员' : props.role || '工作空间成员')

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  }).format(new Date(value))
}

async function loadCommunities(): Promise<void> {
  isLoading.value = true
  listError.value = ''

  try {
    communities.value = await api.get<Community[]>('/communities')
  } catch (error) {
    listError.value = error instanceof Error ? error.message : '无法读取社区项目，请稍后重试。'
  } finally {
    isLoading.value = false
  }
}

function openCreateForm(): void {
  if(!allowLeave())return
  editing.value=null;conflict.value=false;form.value={name:'',address:'',description:''};baseline.value=JSON.stringify(form.value)
  createError.value = ''
  isCreateFormOpen.value = true
  void nextTick(() => { document.getElementById('community-name')?.focus() })
}

function closeCreateForm(): void {
  if (isCreating.value) return
  if(!allowLeave())return
  form.value = { name: '', address: '', description: '' }
  createError.value = ''
  isCreateFormOpen.value = false
  editing.value=null
  void nextTick(() => { document.getElementById('new-community-trigger')?.focus({ preventScroll: true }) })
}

async function createCommunity(): Promise<void> {
  if(isCreating.value || conflict.value)return
  createError.value = ''
  isCreating.value = true

  try {
    const values = {
      name: form.value.name.trim(),
      address: form.value.address.trim() || null,
      description: form.value.description.trim() || null,
    }
    const payload = editing.value ? await api.patch<Community>(`/communities/${editing.value.id}`, {...values,expected_updated_at:editing.value.updated_at}) : await api.post<Community>('/communities',values)
    communities.value = [payload, ...communities.value.filter(c=>c.id!==payload.id)]
    savedNotice.value=editing.value?'社区资料已保存。现有演练中的冻结地图和人员配置不会改变。':'社区已创建，接下来请检查楼栋与道路配置。'
    inspectingId.value=payload.id;baseline.value=JSON.stringify(form.value)
    isCreating.value = false
    resetFilters()
    closeCreateForm()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '保存失败，输入已保留，请重试。'
    conflict.value=error instanceof ApiError && error.status===409
  } finally {
    isCreating.value = false
  }
}

function editCommunity(community:Community){
  if(!allowLeave())return
  editing.value=community;conflict.value=false;createError.value='';savedNotice.value=''
  form.value={name:community.name,address:community.address??'',description:community.description??''}
  baseline.value=JSON.stringify(form.value);isCreateFormOpen.value=true
  void nextTick(()=>{document.getElementById('create-community-panel')?.scrollIntoView({block:'start'});document.getElementById('community-name')?.focus({preventScroll:true})})
}
async function reloadEdited(){
  if(!editing.value || isCreating.value || !window.confirm('载入最新资料将替换当前未保存的输入，是否继续？'))return
  try{const current=await api.get<Community>(`/communities/${editing.value.id}`);baseline.value=JSON.stringify(form.value);editCommunity(current)}
  catch(cause){createError.value=cause instanceof Error?cause.message:'读取失败，请重试。'}
}

async function createDemoCommunity(): Promise<void> {
  demoError.value = ''
  isCreatingDemo.value = true
  try {
    const payload = await api.post<Community>('/communities/demo')
    const existingIndex = communities.value.findIndex((community) => community.id === payload.id)
    if (existingIndex === -1) communities.value = [payload, ...communities.value]
    else communities.value.splice(existingIndex, 1, payload)
    emit('openMap', payload)
  } catch (error) {
    demoError.value = error instanceof Error ? error.message : '主案例社区生成失败，请稍后重试。'
  } finally {
    isCreatingDemo.value = false
  }
}

async function launchThreeDemo(): Promise<void> {
  demoError.value = ''
  isLaunchingThreeDemo.value = true
  try {
    const payload = await api.post<{ community: Community }>('/communities/demo-ready')
    const existingIndex = communities.value.findIndex((community) => community.id === payload.community?.id)
    if (existingIndex === -1) communities.value = [payload.community, ...communities.value]
    else communities.value.splice(existingIndex, 1, payload.community)
    emit('openOperations', payload.community)
  } catch (error) {
    demoError.value = error instanceof Error ? error.message : '三维演练初始化失败，请稍后重试。'
  } finally {
    isLaunchingThreeDemo.value = false
  }
}

onMounted(() => {
  window.addEventListener('beforeunload',beforeUnload)
  void loadCommunities()
})
</script>

<template>
  <section class="project-home">
    <header class="home-header">
      <button class="entry-brand home-brand-button" type="button" aria-label="打开社区项目首页" @click="openSection('projects')"><span class="entry-brand__symbol"><AppIcon name="compass" :size="26" /></span><span>智演安巷<small>社区消防演练平台</small></span></button>
      <nav class="home-nav" aria-label="工作空间导航">
        <button type="button" :aria-current="activeSection === 'projects' ? 'page' : undefined" @click="openSection('projects')"><AppIcon name="building" :size="19" />社区项目<span v-if="!isLoading && !listError">{{ communities.length }}</span></button>
        <button type="button" :aria-current="activeSection === 'training' ? 'page' : undefined" @click="openSection('training')"><AppIcon name="play" :size="19" />示例训练</button>
        <button type="button" :aria-current="activeSection === 'guide' ? 'page' : undefined" @click="openSection('guide')"><AppIcon name="help" :size="19" />使用说明</button>
      </nav>
      <div class="home-account-section">
        <button class="home-account" type="button" aria-label="打开个人中心" :aria-current="activeSection === 'account' ? 'page' : undefined" @click="openSection('account')">
          <span class="home-avatar" aria-hidden="true"><AppIcon name="person" :size="18" /></span>
          <span>{{ username }}<small>{{ roleLabel }}</small></span>
          <AppIcon name="chevron" :size="17" />
        </button>
      </div>
    </header>
    <div id="home-top" class="home-workspace">
      <div class="home-topbar">
        <span>工作空间 <AppIcon name="chevron" :size="14" /> {{ activeSectionName }}</span>
        <button v-if="activeSection === 'projects'" class="entry-button entry-button--primary" type="button" :aria-expanded="isCreateFormOpen" aria-controls="create-community-panel" @click="openCreateForm"><AppIcon name="plus" :size="18" />新建社区项目</button>
      </div>
      <div class="home-content">
      <section v-if="activeSection === 'projects'" class="home-view" aria-labelledby="projects-view-title">
      <div class="home-view-heading"><h1 id="projects-view-title" tabindex="-1">社区项目</h1><p>维护社区资料，检查准备条件，再进入地图与场景配置。</p><button id="new-community-trigger" class="entry-button entry-button--primary" type="button" :disabled="isCreating" :aria-expanded="isCreateFormOpen" aria-controls="create-community-panel" @click="openCreateForm"><AppIcon name="plus" :size="18"/>新建社区项目</button></div>
      <p v-if="savedNotice" class="message" role="status">{{savedNotice}}</p>
      <section v-if="isCreateFormOpen" id="create-community-panel" class="home-create" aria-labelledby="create-title">
        <div class="home-section-heading"><div><h2 id="create-title">{{editing?'编辑社区资料':'创建社区项目'}}</h2><p>维护名称、地址与项目说明，不改写已创建演练的历史数据。</p></div><button class="entry-icon-button" type="button" aria-label="取消编辑" :disabled="isCreating" @click="closeCreateForm"><AppIcon name="close" /></button></div>
        <form class="home-create-form" @submit.prevent="createCommunity">
          <div class="entry-field"><label for="community-name">社区名称</label><input id="community-name" v-model="form.name" maxlength="120" minlength="2" required placeholder="例如：安巷社区" :disabled="isCreating" /></div>
          <div class="entry-field"><label for="community-address">地址 <span>选填</span></label><input id="community-address" v-model="form.address" maxlength="255" placeholder="例如：示例路 18 号" :disabled="isCreating" /></div>
          <div class="entry-field home-create-form__wide"><label for="community-description">项目说明 <span>选填</span></label><textarea id="community-description" v-model="form.description" maxlength="2000" rows="3" placeholder="记录社区特点、演练范围或已知消防隐患。" :disabled="isCreating"></textarea></div>
          <p v-if="createError" class="message message--error home-create-form__wide" role="alert">{{ createError }}</p>
          <div class="home-create-form__actions"><button v-if="conflict" class="entry-button entry-button--outline" type="button" @click="reloadEdited">载入最新资料</button><button class="entry-button entry-button--outline" type="button" :disabled="isCreating" @click="closeCreateForm">取消</button><button class="entry-button entry-button--primary" type="submit" :disabled="isCreating||conflict||!dirty">{{ isCreating ? '正在保存…' : editing?'保存资料':'创建社区项目' }}</button></div>
        </form>
      </section>
      <section id="project-library" class="home-library" aria-labelledby="projects-title">
        <div class="home-section-heading"><h2 id="projects-title">我的社区 <span v-if="!isLoading && !listError" class="home-count">{{ communities.length }}</span></h2><span class="home-sort-note">按最近更新排序</span></div>
        <div class="home-library__tools">
          <div class="home-search"><AppIcon name="search" :size="18" /><input v-model="search" type="search" aria-label="搜索社区项目" placeholder="搜索社区名称、地址或说明" /><button v-if="search" class="entry-icon-button" type="button" aria-label="清空搜索" @click="search = ''"><AppIcon name="close" :size="16" /></button></div>
          <label class="home-filter"><span>项目状态</span><select v-model="statusFilter"><option value="all">全部状态</option><option value="draft">草稿</option><option value="published">已发布</option><option value="archived">已归档</option></select></label>
        </div>
        <div v-if="isLoading" class="home-empty" role="status"><AppIcon name="clock" :size="28" /><h3>正在读取社区项目…</h3><p>即将为你呈现已有社区与演练入口。</p></div>
        <div v-else-if="listError" class="home-empty" role="alert"><h3>暂时无法读取项目</h3><p>{{ listError }}</p><button class="entry-button entry-button--outline" type="button" @click="loadCommunities">重新加载</button></div>
        <div v-else-if="communities.length === 0" class="home-empty"><AppIcon name="building" :size="32" /><h3>从你的第一个社区开始</h3><p>新建社区配置真实底图，或从示例训练直接体验演练。</p><button class="entry-button entry-button--outline" type="button" @click="openCreateForm">创建第一个社区项目</button></div>
        <div v-else-if="filteredCommunities.length === 0" class="home-empty" role="status"><AppIcon name="search" :size="28" /><h3>没有找到符合条件的社区</h3><p>换个关键词，或清除状态筛选试试。</p><button class="entry-button entry-button--outline" type="button" @click="resetFilters">清除筛选</button></div>
        <div v-else class="home-project-list">
          <article v-for="community in filteredCommunities" :key="community.id" class="home-project-row">
            <div class="home-project-mark" aria-hidden="true"><AppIcon name="building" :size="27" /></div>
            <div class="home-project-info"><div><h3>{{ community.name }}</h3><span class="home-status" :data-status="community.status">{{ statusNames[community.status] }}</span></div><p>{{ community.address || '尚未填写社区地址' }}</p><span class="home-project-version">{{ latestVersion(community) }}</span></div>
            <div class="home-project-date"><span>最近更新</span><time :datetime="community.updated_at">{{ formatDate(community.updated_at) }}</time></div>
            <div class="home-project-actions"><button class="entry-link" type="button" :disabled="isCreating" @click="editCommunity(community)">编辑资料</button><button class="entry-link" type="button" :aria-expanded="inspectingId===community.id" @click="inspectingId=inspectingId===community.id?'':community.id">准备检查</button><button class="entry-link" type="button" @click="emit('openMap', community)">编辑地图</button><button class="entry-button entry-button--outline" type="button" @click="emit('openOperations', community)">演练中心<AppIcon name="arrowRight" :size="17" /></button></div>
          </article>
          <p class="home-list-summary" role="status">显示 {{ filteredCommunities.length }} / {{ projectCountLabel }}</p>
          <CommunityReadiness v-if="inspectingId" :key="inspectingId" :community-id="inspectingId" :community-name="communities.find(c=>c.id===inspectingId)?.name" :api-base-url="apiBaseUrl" :access-token="accessToken"/>
        </div>
      </section>
      </section>

      <section v-else-if="activeSection === 'training'" class="home-view" aria-labelledby="training-view-title">
        <div class="home-view-heading"><h1 id="training-view-title" tabindex="-1">示例训练</h1><p>无需配置数据，直接进入一场可以重复推演的社区火灾训练。</p></div>
        <div class="home-training-page">
        <section class="home-feature" aria-labelledby="demo-community-title">
          <div class="home-case-heading"><AppIcon name="play" :size="18" /><h2>夜间充电棚火灾</h2></div>
          <figure class="home-feature__scene">
            <img src="/assets/community-stage-current.png" alt="平台实际渲染的社区模型：住宅立面、充电棚、消防车辆和疏散道路" width="1440" height="892" fetchpriority="high" />
            <figcaption>平台实景截取 · 非实时画面</figcaption>
          </figure>
          <div class="home-feature__copy">
            <h3 id="demo-community-title">安巷社区 · 充电棚火灾</h3>
            <p>夜间充电棚起火。进入三维社区，指挥居民撤离并调度机器人，观察不同路线带来的结果。</p>
            <dl class="home-case-facts"><div><dt>场景</dt><dd>老旧住宅 / 夜间火灾</dd></div><div><dt>任务</dt><dd>路线分配 · 疏散 · 复盘</dd></div></dl>
            <div class="home-feature__actions">
              <button class="entry-button entry-button--primary" type="button" :disabled="isLaunchingThreeDemo || isCreatingDemo" @click="launchThreeDemo"><AppIcon name="play" :size="18" />{{ isLaunchingThreeDemo ? '正在准备三维现场…' : '立即进入三维演练' }}<AppIcon name="arrowRight" :size="18" /></button>
              <button class="entry-link" type="button" :disabled="isCreatingDemo || isLaunchingThreeDemo" @click="createDemoCommunity">{{ isCreatingDemo ? '正在生成案例…' : '编辑案例底图' }}</button>
            </div>
            <p class="home-feature__note">自动准备案例与演练场次，可重复进入。</p>
            <p v-if="demoError" class="message message--error" role="alert">{{ demoError }}</p>
          </div>
        </section>
        <aside class="home-training-checklist" aria-labelledby="training-checklist-title">
          <h2 id="training-checklist-title">这次训练要完成什么</h2>
          <ol>
            <li><span>1</span><div><strong>判断火势与通道</strong><p>查看起火点、烟气和道路风险，再决定从哪里撤离。</p></div></li>
            <li><span>2</span><div><strong>指挥居民与机器人</strong><p>选择人员、分配出口并下发机器人任务。</p></div></li>
            <li><span>3</span><div><strong>比较另一种决策</strong><p>从关键时刻创建分支，观察拥堵、暴露与清点结果。</p></div></li>
          </ol>
          <button class="entry-link" type="button" @click="openSection('guide')">查看完整使用说明<AppIcon name="arrowRight" :size="16" /></button>
        </aside>
        </div>
      </section>

      <section v-else-if="activeSection === 'guide'" class="home-view" aria-labelledby="guide-view-title">
        <div class="home-view-heading"><h1 id="guide-view-title" tabindex="-1">使用说明</h1><p>从社区建模到演练复盘，按一条完整路径使用系统。</p></div>
        <div class="home-guide-page">
          <ol class="home-guide-steps">
            <li><span>1</span><div><h2>准备社区</h2><p>在社区项目中创建或选择社区，编辑楼栋、道路、消防设施和集合点。保存后，地图与三维预览使用同一份数据。</p><button class="entry-link" type="button" @click="openSection('projects')">打开社区项目<AppIcon name="arrowRight" :size="16" /></button></div></li>
            <li><span>2</span><div><h2>进入演练</h2><p>从项目的「演练中心」进入已有场景，也可以使用示例训练自动准备充电棚火灾案例。</p><button class="entry-link" type="button" @click="openSection('training')">打开示例训练<AppIcon name="arrowRight" :size="16" /></button></div></li>
            <li><span>3</span><div><h2>在三维现场下达指令</h2><p>点击居民、道路或机器人，先查看路线、风险和预计影响，再确认封路、疏散或任务指派。</p></div></li>
            <li><span>4</span><div><h2>观察结果并复盘</h2><p>关注排队、拥堵、烟气暴露和机器人执行状态。演练结束后查看证据记录，并从关键决策点创建另一分支比较结果。</p></div></li>
          </ol>
          <aside class="home-guide-note"><AppIcon name="inspect" :size="20" /><div><h2>比赛演示建议</h2><p>先演示一次错误路线，再从同一快照改选出口。评委可以直接看到人员改道、风险变化与评分证据。</p></div></aside>
        </div>
      </section>

      <section v-else class="home-view" aria-labelledby="account-view-title">
        <div class="home-view-heading"><h1 id="account-view-title" tabindex="-1">个人中心</h1><p>查看当前工作空间身份与可用权限。</p></div>
        <div class="home-profile-page">
          <section aria-labelledby="identity-title"><h2 id="identity-title">账户信息</h2><dl><div><dt>账号</dt><dd>{{ username }}</dd></div><div><dt>身份</dt><dd>{{ roleLabel }}</dd></div><div><dt>登录方式</dt><dd>本地工作空间账号</dd></div></dl></section>
          <section aria-labelledby="permission-title"><h2 id="permission-title">当前权限</h2><p>{{ role === 'admin' ? '你可以创建社区、编辑地图与场景、组织三维演练并查看复盘证据。' : '你可以进入已授权的社区项目和演练场景，具体操作由角色权限决定。' }}</p><p class="home-profile-hint">账号与角色由本地系统配置。如需修改权限，请联系系统管理员。</p></section>
          <div class="home-profile-actions"><button class="entry-button entry-button--outline" type="button" aria-label="退出登录" @click="emit('logout')"><AppIcon name="logout" :size="17" />退出工作空间</button></div>
        </div>
      </section>
      <footer class="home-footer"><AppIcon name="inspect" :size="16" /><p>训练模拟，不替代现场消防专业判断。</p></footer>
      </div>
    </div>
  </section>
</template>

<style scoped>
.home-view-heading{display:flex;align-items:center;flex-wrap:wrap;gap:12px 24px}.home-view-heading h1{margin:0}.home-view-heading p{flex:1 1 280px;margin:0}.home-view-heading>button{margin-left:auto;min-height:44px}
.home-project-actions{display:flex;flex-wrap:wrap;gap:12px 16px;justify-content:flex-end;max-width:440px}.home-project-actions button{min-height:44px;font-size:var(--ui-body-size,16px)}
.home-create{scroll-margin-top:20px}.home-create-form input,.home-create-form textarea{font-size:var(--ui-body-size,16px)}.home-create-form__actions{display:flex;align-items:center;justify-content:flex-end;flex-wrap:wrap;gap:12px}
@media(max-width:1100px){.home-project-row{grid-template-columns:auto minmax(0,1fr)}.home-project-actions{grid-column:2;max-width:none;justify-content:flex-start}.home-project-date{grid-column:2}}
@media(max-width:600px){.home-project-row{grid-template-columns:minmax(0,1fr)}.home-project-mark{display:none}.home-project-info,.home-project-date,.home-project-actions{grid-column:1}.home-view-heading>button{margin-left:0}.home-project-actions{gap:8px 16px}}
</style>
