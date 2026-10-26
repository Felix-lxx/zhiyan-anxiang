<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from './AppIcon.vue'
import CommunityLibrary from './CommunityLibrary.vue'
import CommunityPlan from './CommunityPlan.vue'
import CommunityReadiness from './CommunityReadiness.vue'
import TrainingHomeActions from './TrainingHomeActions.vue'
import AccountCenter from './AccountCenter.vue'
import { accountProfile } from '../api/account'
import { createApiClient } from '../api/client'
import type { Community, Scene } from '../domain/models'
import type { DrillIndex, Simulation } from '../domain/drill'
import { csvDocument } from '../domain/csv'
import '../atlas-home.css'
const DigitalTwinArena = defineAsyncComponent(() => import('./DigitalTwinArena.vue'))
const props = defineProps<{ apiBaseUrl:string; accessToken:string; username:string; role:string }>()
const emit = defineEmits<{ logout:[]; openMap:[community:Community]; openOperations:[community:Community] }>()
const api=createApiClient(props.apiBaseUrl,()=>props.accessToken), route=useRoute(), router=useRouter()
type HistoryRow=DrillIndex & {sceneId:string;sceneName:string}
const communities=ref<Community[]>([]), allScenes=ref<Scene[]>([]), history=ref<HistoryRow[]>([])
const showTestData=ref(false)
const fixturePattern=/实跑验收|UI 自动验收|流程验收|图册交互验收|完整任务与智能体实跑|完整决策验收/
const scenes=computed(()=>showTestData.value?allScenes.value:allScenes.value.filter(item=>!fixturePattern.test(item.name)))
watch(showTestData,()=>{sceneId.value=scenes.value.find(s=>s.id===sceneId.value)?.id||scenes.value.find(s=>s.status==='published')?.id||scenes.value[0]?.id||'';void loadHistory()})
const communityId=ref(''), sceneId=ref(''), busy=ref(false), loading=ref(true), error=ref(''), guidance=ref(true)
const section=computed(()=>String(route.query.section || 'home'))
const historySearch=ref(''), historyStatus=ref('all')
const historyScene=ref(''), historyFrom=ref(''), historyTo=ref(''), historySort=ref('newest'), historyPage=ref(1), historyError=ref('')
const dateError=computed(()=>Boolean(historyFrom.value && historyTo.value && historyFrom.value>historyTo.value))
interface HistoryPage {items:HistoryRow[]; total:number; matched:number; page:number; page_size:number; latest_unfinished:HistoryRow|null; latest_review?:HistoryRow|null}
const latestReview = ref<HistoryRow | null>(null)
const historyTotal=ref(0), historyMatched=ref(0), historyLoading=ref(false), unfinished=ref<HistoryRow|null>(null)
const pageCount=computed(()=>Math.max(1,Math.ceil(historyMatched.value/20)))
const visibleHistory=computed(()=>history.value)
const filtered=computed(()=>Boolean(historySearch.value||historyStatus.value!=='all'||historyScene.value||historyFrom.value||historyTo.value||historySort.value!=='newest'))
let historyRequest=0, historyController:AbortController|undefined, historyTimer:ReturnType<typeof setTimeout>|undefined
async function loadHistory(){
 const id=++historyRequest; historyController?.abort()
 if(!communityId.value || (section.value==='history'&&dateError.value)){history.value=[];historyMatched.value=0;historyLoading.value=false;return}
 historyController=new AbortController();historyLoading.value=true;historyError.value='';history.value=[]
 const isHistory=section.value==='history'
 const query=new URLSearchParams({page:String(isHistory?historyPage.value:1),page_size:isHistory?'20':'3'})
 query.set('include_test',String(showTestData.value))
 if(isHistory){
  query.set('search',historySearch.value);query.set('status',historyStatus.value);query.set('sort',historySort.value)
  if(historyScene.value)query.set('scene_id',historyScene.value)
  if(historyFrom.value)query.set('start',new Date(historyFrom.value+'T00:00:00').toISOString())
  if(historyTo.value)query.set('end',new Date(historyTo.value+'T23:59:59.999').toISOString())
 }
 try{
  const result=await api.get<HistoryPage>('/communities/'+communityId.value+'/drill-history?'+query,{signal:historyController.signal})
  if(id!==historyRequest)return
  history.value=result.items;historyTotal.value=result.total;historyMatched.value=result.matched;unfinished.value=result.latest_unfinished;latestReview.value=result.latest_review??null
  if(isHistory)historyPage.value=result.page
 }catch(cause){if(id===historyRequest && !(cause instanceof DOMException&&cause.name==='AbortError'))historyError.value=cause instanceof Error?cause.message:'演练记录读取失败，请重试。'}
 finally{if(id===historyRequest)historyLoading.value=false}
}
function scheduleHistory(){
 if(!['home','history','training'].includes(section.value))return
 historyController?.abort();historyRequest++;historyLoading.value=true;history.value=[]
 if(historyTimer)clearTimeout(historyTimer)
 historyTimer=setTimeout(()=>void loadHistory(),250)
}
watch([historySearch,historyStatus,historyScene,historyFrom,historyTo,historySort],()=>{historyPage.value=1;scheduleHistory()})
watch(historyPage,()=>scheduleHistory())
function clearHistoryFilters(){historySearch.value='';historyStatus.value='all';historyScene.value='';historyFrom.value='';historyTo.value='';historySort.value='newest'}
function exportHistory(){
 const rows=[['演练名称','场景','状态','创建时间','居民人数','演练秒数','得分','关键结论'],...history.value.map(d=>[d.name,d.sceneName,{ready:'待开始',running:'进行中',paused:'已暂停',ended:'已结束'}[d.status]??d.status,date(d.created_at),d.resident_count??'',d.elapsed_seconds,d.score?.total_score??'',resultLabel(d)])]
 const url=URL.createObjectURL(new Blob([csvDocument(rows)],{type:'text/csv;charset=utf-8'})),link=document.createElement('a')
 link.href=url;link.download=`演练记录-第${historyPage.value}页-${new Date().toLocaleDateString('sv-SE')}.csv`;link.click();window.setTimeout(()=>URL.revokeObjectURL(url),1000)
}
const accountName=computed(()=>accountProfile.value?.display_name||props.username)
const community=computed(()=>communities.value.find(c=>c.id===communityId.value))
const scene=computed(()=>scenes.value.find(s=>s.id===sceneId.value))
const scenePreview=ref<Simulation|null>(null)
const previewLoading=ref(false)
const previewMode=ref<'cover'|'spatial'|'plan'>('cover'), previewError=ref('')
const caseReady=computed(()=>!loading.value&&!previewLoading.value&&!previewError.value&&Boolean(scenePreview.value)&&scene.value?.status==='published')
const caseStateLabel=computed(()=>loading.value||previewLoading.value?'正在核对场景':previewError.value?'需要检查配置':caseReady.value?'可以创建演练':'等待准备')
const caseStateDetail=computed(()=>loading.value||previewLoading.value?'正在读取配置与通行模型':previewError.value?'预览未通过，请先处理左侧提示':caseReady.value?'已发布配置将在新场次创建时冻结':'完成场景配置并发布后开始演练')
const parameters=computed(()=>scene.value?.versions[scene.value.versions.length-1]?.parameters)
const isKitchenCase=computed(()=>scene.value?.capabilities?.code==='kitchen_fire'||parameters.value?.fire_source_type==='kitchen')
const caseDescription=computed(()=>isKitchenCase.value
 ? '住宅厨房起火，烟气沿房间、走廊和楼梯传播。逐层查看居民，控制房门、安排护送，并核验燃气关闭和集合清点。'
 : '居民区电动自行车充电棚突发火灾。查看火情与通道，组织人员疏散，调度机器人并记录每一次处置。')
async function chooseCase(code:'kitchen_fire'|'night_charging_shed_fire') {
 const matches=scenes.value.filter(item=>item.capabilities?.code===code)
 const existing=matches.find(item=>item.status==='published')??matches[0]
 if(existing){sceneId.value=existing.id;return}
 busy.value=true;error.value=''
 try{
   const target=community.value??await api.post<Community>('/communities/demo')
   await router.push({name:'scenes',params:{communityId:target.id},query:{case:code}})
 }catch(cause){error.value=cause instanceof Error?cause.message:'案例准备入口暂时不可用，请重试。'}finally{busy.value=false}
}
let generation=0
function navigate(value:string){void router.push({name:'projects',query:value==='home'?{}:{section:value}})}
async function load(){
 loading.value=true;error.value=''
 try{communities.value=await api.get<Community[]>('/communities');const preferred=communityId.value||accountProfile.value?.default_community_id;communityId.value=communities.value.find(c=>c.id===preferred)?.id||communities.value[0]?.id||'';if(communityId.value)await loadScenes();else{allScenes.value=[];history.value=[];sceneId.value=''}}
 catch(e){error.value=e instanceof Error?e.message:'读取失败，请重试。'}finally{loading.value=false}
}
async function loadScenes(){
 if(historyTimer)clearTimeout(historyTimer)
 historyController?.abort();historyRequest++;unfinished.value=null;latestReview.value=null;historyTotal.value=0;historyMatched.value=0
 const previousScene=sceneId.value, id=++generation;allScenes.value=[];history.value=[];sceneId.value='';error.value='';historyError.value='';historyPage.value=1
 try{
 const result=await api.get<Scene[]>('/communities/'+communityId.value+'/scenes');if(id!==generation)return
 allScenes.value=result;sceneId.value=scenes.value.find(s=>s.id===previousScene)?.id||scenes.value.find(s=>s.status==='published')?.id||scenes.value[0]?.id||''
 if(!result.some(s=>s.id===historyScene.value))historyScene.value=''
 await loadHistory()
 }catch(e){if(id===generation)error.value=e instanceof Error?e.message:'读取场景失败。'}
}
async function prepare(){
 if(community.value){await router.push({name:'scenes',params:{communityId:community.value.id},query:{scene:sceneId.value||undefined}});return}
 busy.value=true;error.value=''
 try{const c=await api.post<Community>('/communities/demo');await router.push({name:'scenes',params:{communityId:c.id}})}
 catch(e){error.value=e instanceof Error?e.message:'创建失败。'}finally{busy.value=false}
}
async function enter(){
 if(previewError.value){await prepare();return}
 if(scene.value?.status==='published'&&community.value){await router.push({name:'operations',params:{communityId:community.value.id},query:{scene:scene.value.id,new:'1'}});return}
 if(community.value&&scene.value){await prepare();return}
 busy.value=true;error.value=''
 try{const result=await api.post<{community:Community}>('/communities/demo-ready');emit('openOperations',result.community)}
 catch(e){error.value=e instanceof Error?e.message:'准备演练失败。'}finally{busy.value=false}
}
function replay(d:HistoryRow){if(community.value)void router.push({name:'operations',params:{communityId:community.value.id},query:{scene:d.sceneId,drill:d.id,mode:'replay'}})}
function continueRun(d:HistoryRow){if(community.value)void router.push({name:'operations',params:{communityId:community.value.id},query:{scene:d.sceneId,drill:d.id}})}
function date(v?:string){return v?new Date(v).toLocaleString('zh-CN',{hour12:false}):'尚未开始'}
function resultLabel(d:DrillIndex){return d.score?.recommendations[0]||({running:'演练进行中',paused:'演练已暂停',ready:'等待启动'}[d.status]??'等待复盘')}
watch([sceneId,section],async([id,current],_,onCleanup)=>{previewLoading.value=false;scenePreview.value=null;previewMode.value='cover';previewError.value='';if(!id||!['home','training'].includes(current))return;previewLoading.value=true;let cancelled=false;onCleanup(()=>{cancelled=true});try{const result=await api.get<{simulation:Simulation}>('/scenes/'+id+'/preview?minute=0');if(!cancelled){scenePreview.value=result.simulation;if(isKitchenCase.value)previewMode.value='spatial'}}catch(cause){if(!cancelled)previewError.value=cause instanceof Error?cause.message:'场景预览读取失败，请在场景准备中检查配置。'}finally{if(!cancelled)previewLoading.value=false}})
watch(section,(v,previous)=>{if(previous==='account'&&accountProfile.value?.default_community_id)communityId.value=accountProfile.value.default_community_id;if(v==='home'||v==='history')void load()})
onBeforeUnmount(()=>{generation++;historyRequest++;historyController?.abort();if(historyTimer)clearTimeout(historyTimer)})
onMounted(load)
</script>
<template>
<main id="main-content" class="atlas-home">
 <aside class="atlas-sidebar">
  <button class="atlas-sidebar__brand" title="智演安巷——面向老旧小区消防治理的数字孪生与智能决策平台" @click="navigate('home')"><AppIcon name="building" :size="44"/><strong>智演安巷</strong><small>消防治理智能决策平台</small></button>
  <nav aria-label="工作空间导航"><button :aria-current="section==='home'?'page':undefined" @click="navigate('home')"><AppIcon name="compass"/>演练首页</button><button @click="prepare"><AppIcon name="tasks"/>场景准备</button><button :aria-current="section==='history'?'page':undefined" @click="navigate('history')"><AppIcon name="clock"/>复盘记录</button><button :aria-current="section==='communities'?'page':undefined" @click="navigate('communities')"><AppIcon name="building"/>社区管理</button><button :aria-current="section==='guide'?'page':undefined" @click="navigate('guide')"><AppIcon name="help"/>使用说明</button></nav>
  <div class="atlas-sidebar__foot"><p>演练于平时<br/>平安在万家</p><button :aria-current="section==='account'?'page':undefined" @click="navigate('account')"><AppIcon name="person" :size="18"/>个人中心</button></div>
 </aside>
 <div class="atlas-home__body">
  <header class="atlas-home__bar"><div><strong>{{community?.name.split(' · ')[0]||'安巷社区'}}</strong><span>老旧小区消防治理数字孪生与智能决策</span></div><div><span class="atlas-online"><i :data-error="Boolean(error)"></i>{{error?'连接待恢复':loading?'正在连接':'系统在线'}}</span><button aria-label="打开个人中心" @click="navigate('account')"><AppIcon name="person"/><span class="atlas-account-name">{{accountName}}</span><AppIcon name="chevron" :size="16"/></button></div></header>
  <section v-if="section==='home'||section==='history'||section==='training'" class="atlas-home__content">
   <header class="atlas-home__title"><h1>{{section==='history'?'复盘记录':'演练工作台'}}</h1><p>以真实场景锻炼应急能力，让社区更安全</p><label v-if="communities.length>1" class="atlas-community-switch"><span>社区</span><select v-model="communityId" @change="loadScenes"><option v-for="c in communities" :key="c.id" :value="c.id">{{c.name}}</option></select></label></header>
   <label class="home-test-data"><input v-model="showTestData" type="checkbox"/>显示验收场景与试验记录</label>
   <p v-if="error" class="atlas-home__error" role="alert">{{error}}<button @click="load">重新加载</button></p>
   <TrainingHomeActions v-if="section!=='history'" :api-base-url="apiBaseUrl" :access-token="accessToken" :unfinished="unfinished" :review="latestReview" :loading="loading||historyLoading" :busy="busy" @resume="unfinished&&continueRun(unfinished)" @prepare="prepare" @review="latestReview&&replay(latestReview)" />
   <nav v-if="section!=='history'" class="home-case-switch" aria-label="选择火灾案例">
     <button type="button" :disabled="loading||busy" :aria-pressed="Boolean(scene)&&!isKitchenCase" @click="chooseCase('night_charging_shed_fire')"><AppIcon name="fire"/><span><strong>充电棚火灾</strong><small>室外通道 · 资源调度 · 分流疏散</small></span></button>
     <button type="button" :disabled="loading||busy" :aria-pressed="Boolean(scene)&&isKitchenCase" @click="chooseCase('kitchen_fire')"><AppIcon name="building"/><span><strong>住宅厨房火灾</strong><small>室内分区 · 房门控制 · 逐层护送</small></span></button>
   </nav>
   <div v-if="section!=='history'" class="atlas-case">
    <figure class="atlas-case__visual"><CommunityPlan v-if="previewMode==='plan'&&scenePreview" :simulation="scenePreview"/><DigitalTwinArena v-else-if="previewMode==='spatial'&&scenePreview" :key="sceneId" :simulation="scenePreview" :robot="null" status="paused" :elapsed-seconds="0" compact :interactive="false" :camera-enabled="false"/><img v-else-if="!isKitchenCase" src="/assets/atlas-community-night.png" alt="夜间充电棚火灾场景效果图" fetchpriority="high"/><div v-else class="home-case-loading" role="status">正在读取厨房空间…</div><span class="atlas-case__location"><AppIcon name="target" :size="16"/>{{community?.name.split(' · ')[0]||'安巷社区'}} · {{previewMode==='cover'?'场景效果图':previewMode==='spatial'?'实际配置 · 拖动旋转、滚轮缩放':'实际配置 · 平面路网'}}</span><div v-if="previewError" class="atlas-case__preview-error" role="status">{{previewError}}<button @click="prepare">检查场景配置</button></div><div class="atlas-case__views"><button v-if="!isKitchenCase" :aria-pressed="previewMode==='cover'" @click="previewMode='cover'">效果图</button><button :aria-pressed="previewMode==='spatial'" :disabled="!scenePreview" @click="previewMode='spatial'">三维预览</button><button :aria-pressed="previewMode==='plan'" :disabled="!scenePreview" @click="previewMode='plan'">平面图</button></div></figure>
    <article class="atlas-case__details"><div class="atlas-case__select"><span>预设场景</span><select v-if="scenes.length" v-model="sceneId" aria-label="更换场景"><option v-for="s in scenes" :key="s.id" :value="s.id">{{s.name}}</option></select><button v-else @click="prepare">准备场景<AppIcon name="arrowRight" :size="16"/></button></div><h2>{{scene?.name||'夜间充电棚火灾'}}</h2><p>{{caseDescription}}</p>
     <dl><div><AppIcon name="users"/><dt>涉及人数</dt><dd>{{scenePreview?.summary.total??parameters?.resident_count??'—'}} <small>人</small></dd><span>含重点关注居民</span></div><div><AppIcon name="logout"/><dt>可用疏散出口</dt><dd>{{scenePreview?.road_network?.nodes.filter(n=>n.is_exit).length??'—'}} <small>个</small></dd><span>由社区路网确定</span></div><div><AppIcon name="robot"/><dt>机器人状态</dt><dd>{{scene?'1 台':'待部署'}}</dd><span>{{scene?'巡检广播机器人 · 场景预设':'开始后载入场景'}}</span></div></dl>
     <div class="atlas-case__ready"><AppIcon :name="caseReady?'check':'clock'" :size="25"/><strong>{{caseStateLabel}}</strong><span>{{caseStateDetail}}</span></div><button class="atlas-case__enter" :disabled="busy||loading||previewLoading" @click="enter"><AppIcon name="play"/>{{busy?'正在准备…':previewError?'检查场景配置':scene&&scene.status!=='published'?'继续场景准备':'进入演练'}}<AppIcon name="arrowRight"/></button>
    </article>
   </div>
   <CommunityReadiness v-if="section!=='history'&&community" :community-id="community.id" :api-base-url="apiBaseUrl" :access-token="accessToken"/>
   <section class="atlas-history">
    <header><h2>{{section==='history'?'演练记录':'最近演练'}}</h2><button v-if="section!=='history'" @click="navigate('history')">查看全部记录<AppIcon name="arrowRight" :size="18"/></button><button v-else :disabled="loading" @click="load">刷新记录<AppIcon name="refresh" :size="18"/></button></header>
    <div v-if="section==='history'" class="atlas-history__filters"><label>搜索演练<input v-model="historySearch" type="search" placeholder="输入演练名称" /></label><label>演练状态<select v-model="historyStatus" aria-label="演练状态"><option value="all">全部状态</option><option value="ready">待开始</option><option value="running">进行中</option><option value="paused">已暂停</option><option value="ended">已结束</option></select></label><label>所属场景<select v-model="historyScene" aria-label="所属场景"><option value="">全部场景</option><option v-for="s in scenes" :key="s.id" :value="s.id">{{s.name}}</option></select></label><label>开始日期<input v-model="historyFrom" type="date"/></label><label>截止日期<input v-model="historyTo" type="date" :min="historyFrom||undefined"/></label><label>排序<select v-model="historySort" aria-label="排序"><option value="newest">最近创建优先</option><option value="oldest">最早创建优先</option><option value="score">得分从高到低</option></select></label><div class="history-filter-actions"><span role="status">{{ historyMatched }} / {{ historyTotal }} 条</span><button v-if="filtered" @click="clearHistoryFilters">清除筛选</button><button type="button" :disabled="!history.length||historyLoading||loading||Boolean(historyError)" @click="exportHistory">导出本页 CSV</button></div></div>
    <p v-if="historyError" class="atlas-home__error" role="alert">{{historyError}}<button @click="load">重新读取</button></p><p v-if="dateError" role="alert">截止日期不能早于开始日期。</p>
    <div class="atlas-history__scroll" :aria-busy="historyLoading" role="region" aria-label="演练记录列表，窄屏可横向滚动" tabindex="0"><table><thead><tr><th>序号</th><th>演练场景</th><th>演练时间</th><th>参与人数</th><th>得分</th><th>关键结论</th><th>操作</th></tr></thead><tbody><tr v-for="(d,i) in visibleHistory" :key="d.id"><td>{{String((section==='history'?(historyPage-1)*20:0)+i+1).padStart(2,'0')}}</td><td><strong>{{d.name}}</strong><small class="history-scene-name">{{d.sceneName}}</small></td><td>{{date(d.created_at)}}</td><td>{{d.resident_count??'—'}} 人</td><td class="atlas-history__score">{{d.score?.total_score??'—'}}<small v-if="d.score"> 分</small></td><td>{{resultLabel(d)}}</td><td><div class="atlas-history__actions"><button v-if="d.status!=='ended'" class="atlas-history__action" type="button" @click="continueRun(d)"><span>{{d.status==='ready'?'开始演练':'继续演练'}}</span><AppIcon name="play" :size="16"/></button><button class="atlas-history__action" type="button" @click="replay(d)"><span>查看复盘</span><AppIcon name="arrowRight" :size="16"/></button></div></td></tr><tr v-if="!visibleHistory.length"><td colspan="7">{{loading||historyLoading?'正在读取演练记录…':historyTotal?'没有匹配的记录，请调整搜索词或状态。':'尚无演练记录。完成首次演练后，将在这里保留过程与证据。'}}</td></tr></tbody></table></div>
    <nav v-if="section==='history'&&historyMatched" class="history-pagination" aria-label="演练记录分页"><span>每页 20 条 · 第 {{historyPage}} / {{pageCount}} 页</span><button type="button" :disabled="historyLoading||historyPage<=1" @click="historyPage--">上一页</button><button type="button" :disabled="historyLoading||historyPage>=pageCount" @click="historyPage++">下一页</button></nav>
   </section>
   <div v-if="guidance&&section!=='history'" class="atlas-home__guide"><AppIcon name="help"/><p><strong>首次使用提示：</strong>建议先在「场景准备」中熟悉社区地图、人员配置和设备，再开始正式演练。</p><button @click="prepare">前往场景准备<AppIcon name="arrowRight" :size="16"/></button><button aria-label="关闭首次使用提示" @click="guidance=false"><AppIcon name="close" :size="16"/></button></div>
  </section>
  <AccountCenter v-else-if="section==='account'" :api-base-url="apiBaseUrl" :access-token="accessToken" @logout="emit('logout')"/>
  <CommunityLibrary v-else :key="section" class="atlas-library" v-bind="props" @logout="emit('logout')" @open-map="c=>emit('openMap',c)" @open-operations="c=>emit('openOperations',c)"/>
 </div>
</main>
</template>

<style scoped>
.home-test-data { display:flex; align-items:center; gap:10px; min-height:44px; margin-bottom:16px; font-size:14px; color:var(--text-secondary); }
.home-test-data input { width:18px; height:18px; accent-color:var(--action-primary); }
.home-case-switch { display:flex; flex-wrap:wrap; gap:12px; margin-bottom:20px; }
.home-case-switch button { flex:1 1 260px; display:flex; align-items:center; gap:14px; text-align:left; padding:14px 18px; min-height:64px; border:1px solid var(--border-default); border-radius:8px; background:var(--surface-panel); color:var(--text-primary); }
.home-case-switch button[aria-pressed=true] { background:var(--color-brand-100); border-color:var(--action-primary); }
.home-case-switch strong,.home-case-switch small { display:block; }
.home-case-switch strong { font-size:18px; }.home-case-switch small { font-size:14px; margin-top:4px; }
.home-case-loading { display:grid; place-content:center; height:100%; min-height:240px; color:var(--text-primary); background:var(--surface-page); }
.home-resume{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:18px 0;border-bottom:1px solid var(--border-default);font-size:var(--ui-body-size,16px)}.home-resume p{margin:4px 0 0;color:var(--text-secondary);overflow-wrap:anywhere}.home-resume button{display:flex;align-items:center;gap:8px;flex:none;min-height:44px;padding:8px 14px;background:var(--surface-panel);border:1px solid var(--border-default);border-radius:var(--radius-sm);color:var(--text-primary)}
.atlas-history__filters{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;align-items:end;margin-bottom:20px}.atlas-history__filters label{display:grid;gap:6px;min-width:0;font-size:var(--ui-meta-size,14px)}.atlas-history__filters input,.atlas-history__filters select{min-width:0;width:100%;min-height:44px;font-size:var(--ui-body-size,16px);padding:8px 12px;border:1px solid var(--border-default);border-radius:var(--radius-sm);background:var(--surface-panel);color:var(--text-primary)}
.history-filter-actions{grid-column:1/-1;display:flex;align-items:center;gap:12px 24px;flex-wrap:wrap}.history-filter-actions span{margin-right:auto}.history-filter-actions button,.history-pagination button{min-height:44px;border:1px solid var(--border-default);border-radius:var(--radius-sm);padding:8px 14px;font-size:var(--ui-body-size,16px)}.history-pagination{display:flex;align-items:center;justify-content:flex-end;gap:12px;flex-wrap:wrap;margin-top:18px}.history-pagination span{margin-right:auto;font-size:var(--ui-meta-size,14px)}.history-scene-name{display:block;margin-top:4px;font-size:var(--ui-meta-size,14px);color:var(--text-secondary)}.atlas-history button:disabled{opacity:.5;cursor:not-allowed}
@media(max-width:760px){.atlas-history__filters{grid-template-columns:repeat(2,minmax(0,1fr))}.home-resume{align-items:flex-start;flex-wrap:wrap}.home-resume button{margin-left:auto}}
@media(max-width:600px){.atlas-sidebar nav button{white-space:normal;padding-inline:6px;font-size:14px;gap:6px}}
@media(max-width:540px){
 .atlas-home{grid-template-columns:minmax(0,1fr)}
 .atlas-sidebar{min-width:0;max-width:100%;padding-inline:8px}
 .atlas-sidebar nav{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));min-width:0;gap:4px;width:100%}
 .atlas-sidebar nav button{min-width:0;padding-inline:2px;overflow-wrap:anywhere}
 .atlas-home__bar>div{min-width:0;flex-wrap:wrap}
 .atlas-home__bar{height:auto;min-height:55px;flex-wrap:wrap;padding-block:10px}
}
@media(max-width:420px){.atlas-history__filters{grid-template-columns:minmax(0,1fr)}}
</style>
