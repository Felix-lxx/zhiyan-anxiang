<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from './AppIcon.vue'
import CommunityLibrary from './CommunityLibrary.vue'
import CommunityPlan from './CommunityPlan.vue'
import AccountCenter from './AccountCenter.vue'
import { accountProfile } from '../api/account'
import { createApiClient } from '../api/client'
import type { Community, Scene } from '../domain/models'
import type { DrillIndex, Simulation } from '../domain/drill'
import '../atlas-home.css'
const DigitalTwinArena = defineAsyncComponent(() => import('./DigitalTwinArena.vue'))
const props = defineProps<{ apiBaseUrl:string; accessToken:string; username:string; role:string }>()
const emit = defineEmits<{ logout:[]; openMap:[community:Community]; openOperations:[community:Community] }>()
const api=createApiClient(props.apiBaseUrl,()=>props.accessToken), route=useRoute(), router=useRouter()
type HistoryRow=DrillIndex & {sceneId:string}
const communities=ref<Community[]>([]), scenes=ref<Scene[]>([]), history=ref<HistoryRow[]>([])
const communityId=ref(''), sceneId=ref(''), busy=ref(false), loading=ref(true), error=ref(''), guidance=ref(true)
const section=computed(()=>String(route.query.section || 'home'))
const historySearch=ref(''), historyStatus=ref('all')
const filteredHistory=computed(()=>history.value.filter(item=>(historyStatus.value==='all'||item.status===historyStatus.value)&&item.name.toLocaleLowerCase().includes(historySearch.value.trim().toLocaleLowerCase())))
const visibleHistory=computed(()=>section.value==='history'?filteredHistory.value:history.value.slice(0,3))
const accountName=computed(()=>accountProfile.value?.display_name||props.username)
const community=computed(()=>communities.value.find(c=>c.id===communityId.value))
const scene=computed(()=>scenes.value.find(s=>s.id===sceneId.value))
const scenePreview=ref<Simulation|null>(null)
const previewMode=ref<'cover'|'spatial'|'plan'>('cover'), previewError=ref('')
const parameters=computed(()=>scene.value?.versions[scene.value.versions.length-1]?.parameters)
let generation=0
function navigate(value:string){void router.push({name:'projects',query:value==='home'?{}:{section:value}})}
async function load(){
 loading.value=true;error.value=''
 try{communities.value=await api.get<Community[]>('/communities');const preferred=communityId.value||accountProfile.value?.default_community_id;communityId.value=communities.value.find(c=>c.id===preferred)?.id||communities.value[0]?.id||'';if(communityId.value)await loadScenes();else{scenes.value=[];history.value=[];sceneId.value=''}}
 catch(e){error.value=e instanceof Error?e.message:'读取失败，请重试。'}finally{loading.value=false}
}
async function loadScenes(){
 const id=++generation;scenes.value=[];history.value=[];sceneId.value='';error.value=''
 try{
 const result=await api.get<Scene[]>('/communities/'+communityId.value+'/scenes');if(id!==generation)return
 scenes.value=result;sceneId.value=result.find(s=>s.status==='published')?.id||result[0]?.id||''
 const lists=await Promise.all(result.map(async s=>(await api.get<HistoryRow[]>('/scenes/'+s.id+'/drills?summary=true')).map(d=>({...d,sceneId:s.id}))))
 if(id===generation)history.value=lists.flat().sort((a,b)=>Date.parse(b.created_at||'')-Date.parse(a.created_at||''))
 }catch(e){if(id===generation)error.value=e instanceof Error?e.message:'读取场景失败。'}
}
async function prepare(){
 if(community.value){await router.push({name:'scenes',params:{communityId:community.value.id},query:{scene:sceneId.value||undefined}});return}
 busy.value=true;error.value=''
 try{const c=await api.post<Community>('/communities/demo');await router.push({name:'scenes',params:{communityId:c.id}})}
 catch(e){error.value=e instanceof Error?e.message:'创建失败。'}finally{busy.value=false}
}
async function enter(){
 if(scene.value?.status==='published'&&community.value){await router.push({name:'operations',params:{communityId:community.value.id},query:{scene:scene.value.id,autostart:'1'}});return}
 if(community.value&&scene.value){await prepare();return}
 busy.value=true;error.value=''
 try{const result=await api.post<{community:Community}>('/communities/demo-ready');emit('openOperations',result.community)}
 catch(e){error.value=e instanceof Error?e.message:'准备演练失败。'}finally{busy.value=false}
}
function replay(d:HistoryRow){if(community.value)void router.push({name:'operations',params:{communityId:community.value.id},query:{scene:d.sceneId,drill:d.id,mode:'replay'}})}
function continueRun(d:HistoryRow){if(community.value)void router.push({name:'operations',params:{communityId:community.value.id},query:{scene:d.sceneId,drill:d.id}})}
function date(v?:string){return v?new Date(v).toLocaleString('zh-CN',{hour12:false}):'尚未开始'}
function resultLabel(d:DrillIndex){return d.score?.recommendations[0]||({running:'演练进行中',paused:'演练已暂停',ready:'等待启动'}[d.status]??'等待复盘')}
watch(sceneId,async(id,_,onCleanup)=>{scenePreview.value=null;previewMode.value='cover';previewError.value='';if(!id)return;let cancelled=false;onCleanup(()=>{cancelled=true});try{const result=await api.get<{simulation:Simulation}>('/scenes/'+id+'/preview?minute=0');if(!cancelled)scenePreview.value=result.simulation}catch(cause){if(!cancelled)previewError.value=cause instanceof Error?cause.message:'场景预览读取失败，请在场景准备中检查配置。'}})
watch(section,(v,previous)=>{if(previous==='account'&&accountProfile.value?.default_community_id)communityId.value=accountProfile.value.default_community_id;if(v==='home'||v==='history')void load()})
onMounted(load)
</script>
<template>
<main id="main-content" class="atlas-home">
 <aside class="atlas-sidebar">
  <button class="atlas-sidebar__brand" @click="navigate('home')"><AppIcon name="building" :size="44"/><strong>智演安巷</strong><small>老旧小区消防应急演练平台</small></button>
  <nav aria-label="工作空间导航"><button :aria-current="section==='home'?'page':undefined" @click="navigate('home')"><AppIcon name="compass"/>演练首页</button><button @click="prepare"><AppIcon name="tasks"/>场景准备</button><button :aria-current="section==='history'?'page':undefined" @click="navigate('history')"><AppIcon name="clock"/>复盘记录</button><button :aria-current="section==='guide'?'page':undefined" @click="navigate('guide')"><AppIcon name="help"/>使用说明</button></nav>
  <div class="atlas-sidebar__foot"><p>演练于平时<br/>平安在万家</p><button :aria-current="section==='communities'?'page':undefined" @click="navigate('communities')"><AppIcon name="building" :size="18"/>社区管理</button><button :aria-current="section==='account'?'page':undefined" @click="navigate('account')"><AppIcon name="person" :size="18"/>个人中心</button></div>
 </aside>
 <div class="atlas-home__body">
  <header class="atlas-home__bar"><div><strong>{{community?.name.split(' · ')[0]||'安巷社区'}}</strong><span>老旧社区消防应急演练平台</span></div><div><span class="atlas-online"><i :data-error="Boolean(error)"></i>{{error?'连接待恢复':loading?'正在连接':'系统在线'}}</span><button aria-label="打开个人中心" @click="navigate('account')"><AppIcon name="person"/><span class="atlas-account-name">{{accountName}}</span><AppIcon name="chevron" :size="16"/></button></div></header>
  <section v-if="section==='home'||section==='history'||section==='training'" class="atlas-home__content">
   <header class="atlas-home__title"><h1>{{section==='history'?'复盘记录':'演练工作台'}}</h1><p>以真实场景锻炼应急能力，让社区更安全</p><label v-if="communities.length>1" class="atlas-community-switch"><span>社区</span><select v-model="communityId" @change="loadScenes"><option v-for="c in communities" :key="c.id" :value="c.id">{{c.name}}</option></select></label></header>
   <p v-if="error" class="atlas-home__error" role="alert">{{error}}<button @click="load">重新加载</button></p>
   <div v-if="section!=='history'" class="atlas-case">
    <figure class="atlas-case__visual"><CommunityPlan v-if="previewMode==='plan'&&scenePreview" :simulation="scenePreview"/><DigitalTwinArena v-else-if="previewMode==='spatial'&&scenePreview" :key="sceneId" :simulation="scenePreview" :robot="null" status="paused" :elapsed-seconds="0" compact :interactive="false" :camera-enabled="false"/><img v-else src="/assets/atlas-community-night.png" alt="夜间充电棚火灾场景效果图" fetchpriority="high"/><span class="atlas-case__location"><AppIcon name="target" :size="16"/>{{community?.name.split(' · ')[0]||'安巷社区'}} · {{previewMode==='cover'?'场景效果图':previewMode==='spatial'?'实际配置 · 拖动旋转、滚轮缩放':'实际配置 · 平面路网'}}</span><div v-if="previewError" class="atlas-case__preview-error" role="status">{{previewError}}<button @click="prepare">检查场景配置</button></div><div class="atlas-case__views"><button :aria-pressed="previewMode==='cover'" @click="previewMode='cover'">效果图</button><button :aria-pressed="previewMode==='spatial'" :disabled="!scenePreview" @click="previewMode='spatial'">三维预览</button><button :aria-pressed="previewMode==='plan'" :disabled="!scenePreview" @click="previewMode='plan'">平面图</button></div></figure>
    <article class="atlas-case__details"><div class="atlas-case__select"><span>预设场景</span><select v-if="scenes.length" v-model="sceneId" aria-label="更换场景"><option v-for="s in scenes" :key="s.id" :value="s.id">{{s.name}}</option></select><button v-else @click="prepare">准备场景<AppIcon name="arrowRight" :size="16"/></button></div><h2>{{scene?.name||'夜间充电棚火灾'}}</h2><p>居民区电动自行车充电棚突发火灾。查看火情与通道，组织人员疏散，调度机器人并记录每一次处置。</p>
     <dl><div><AppIcon name="users"/><dt>涉及人数</dt><dd>{{scenePreview?.summary.total??parameters?.resident_count??'—'}} <small>人</small></dd><span>含重点关注居民</span></div><div><AppIcon name="logout"/><dt>可用疏散出口</dt><dd>{{scenePreview?.road_network?.nodes.filter(n=>n.is_exit).length??'—'}} <small>个</small></dd><span>由社区路网确定</span></div><div><AppIcon name="robot"/><dt>机器人状态</dt><dd>{{scene?'1 台':'待部署'}}</dd><span>{{scene?'巡检广播机器人 · 场景预设':'开始后载入场景'}}</span></div></dl>
     <div class="atlas-case__ready"><AppIcon :name="scene?.status==='published'?'check':'clock'" :size="25"/><strong>{{loading?'读取场景':scene?.status==='published'?'准备就绪':'等待准备'}}</strong><span>{{scene?.status==='published'?'场景已冻结，可以开始演练':'完成场景配置后开始演练'}}</span></div><button class="atlas-case__enter" :disabled="busy||loading" @click="enter"><AppIcon name="play"/>{{busy?'正在准备…':scene&&scene.status!=='published'?'继续场景准备':'进入演练'}}<AppIcon name="arrowRight"/></button>
    </article>
   </div>
   <section class="atlas-history">
    <header><h2>{{section==='history'?'演练记录':'最近演练'}}</h2><button v-if="section!=='history'" @click="navigate('history')">查看全部记录<AppIcon name="arrowRight" :size="18"/></button><button v-else :disabled="loading" @click="load">刷新记录<AppIcon name="refresh" :size="18"/></button></header>
    <div v-if="section==='history'" class="atlas-history__filters"><label>搜索演练<input v-model="historySearch" type="search" placeholder="输入演练名称" /></label><label>演练状态<select v-model="historyStatus"><option value="all">全部状态</option><option value="ready">待开始</option><option value="running">进行中</option><option value="paused">已暂停</option><option value="ended">已结束</option></select></label><span role="status">{{ filteredHistory.length }} / {{ history.length }} 条</span><button v-if="historySearch || historyStatus!=='all'" @click="historySearch='';historyStatus='all'">清除筛选</button></div>
    <div class="atlas-history__scroll" role="region" aria-label="演练记录列表，窄屏可横向滚动" tabindex="0"><table><thead><tr><th>序号</th><th>演练场景</th><th>演练时间</th><th>参与人数</th><th>得分</th><th>关键结论</th><th>操作</th></tr></thead><tbody><tr v-for="(d,i) in visibleHistory" :key="d.id"><td>{{String(i+1).padStart(2,'0')}}</td><td>{{d.name}}</td><td>{{date(d.created_at)}}</td><td>{{d.resident_count??'—'}} 人</td><td class="atlas-history__score">{{d.score?.total_score??'—'}}<small v-if="d.score"> 分</small></td><td>{{resultLabel(d)}}</td><td><div class="atlas-history__actions"><button v-if="d.status!=='ended'" class="atlas-history__action" type="button" @click="continueRun(d)"><span>{{d.status==='ready'?'开始演练':'继续演练'}}</span><AppIcon name="play" :size="16"/></button><button class="atlas-history__action" type="button" @click="replay(d)"><span>查看复盘</span><AppIcon name="arrowRight" :size="16"/></button></div></td></tr><tr v-if="!visibleHistory.length"><td colspan="7">{{loading?'正在读取演练记录…':history.length?'没有匹配的记录，请调整搜索词或状态。':'尚无演练记录。完成首次演练后，将在这里保留过程与证据。'}}</td></tr></tbody></table></div>
   </section>
   <div v-if="guidance&&section!=='history'" class="atlas-home__guide"><AppIcon name="help"/><p><strong>首次使用提示：</strong>建议先在「场景准备」中熟悉社区地图、人员配置和设备，再开始正式演练。</p><button @click="prepare">前往场景准备<AppIcon name="arrowRight" :size="16"/></button><button aria-label="关闭首次使用提示" @click="guidance=false"><AppIcon name="close" :size="16"/></button></div>
  </section>
  <AccountCenter v-else-if="section==='account'" :api-base-url="apiBaseUrl" :access-token="accessToken" @logout="emit('logout')"/>
  <CommunityLibrary v-else :key="section" class="atlas-library" v-bind="props" @logout="emit('logout')" @open-map="c=>emit('openMap',c)" @open-operations="c=>emit('openOperations',c)"/>
 </div>
</main>
</template>
