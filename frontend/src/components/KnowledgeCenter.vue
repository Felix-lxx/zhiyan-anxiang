<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { createApiClient } from '../api/client'
import type { KnowledgeDocument, KnowledgeResult, KnowledgeObservation as Observation } from '../domain/knowledge'
import KnowledgeEvidence from './KnowledgeEvidence.vue'
import KnowledgeObservation from './KnowledgeObservation.vue'
import SpeechInput from './SpeechInput.vue'
import AppIcon from './AppIcon.vue'
import '../knowledge.css'

const props = defineProps<{ apiBaseUrl:string; accessToken:string }>()
const route = useRoute(), router=useRouter(), api = createApiClient(props.apiBaseUrl, () => props.accessToken)
const documents = ref<KnowledgeDocument[]>([]), selected = ref<KnowledgeDocument | null>(null)
const communities = ref<Array<{id:string;name:string}>>([]), community = ref(''), scenario = ref('all')
const mode = ref<'detail'|'new'|'search'>('detail'), page = ref(1), total = ref(0), query = ref('厨房烟气与房门应该怎样核对？')
const result = ref<KnowledgeResult | null>(null), error = ref(''), notice = ref(''), busy = ref(false), loading = ref(false)
const semantic = ref(false), embeddingAvailable = ref(false), allowEmbedding = ref(false), reviewed = ref(false)
const versionId = ref(''), revisionOf = ref('')
const confirmDelete = ref(false)
const voiceBusy=ref(false)
let generation = 0, controller:AbortController | undefined, disposed = false
const blank = () => ({title:'',content:'',source_url:'',publisher:'',category:'community_plan',filename:'',file_base64:'',valid_date:''})
const form = ref(blank())
const version = computed(() => selected.value?.versions.find(v => v.id===versionId.value) ?? selected.value?.versions[0])
const statuses:Record<string,string> = {draft:'草稿',review:'待审核',published:'已发布',failed:'提取失败',withdrawn:'已停用',superseded:'历史版本',expired:'已过期'}
const versionLabel = (v?:{status:string;effective_status?:string}) => statuses[v?.effective_status??v?.status??'draft']
const categories:Record<string,string> = {official_summary:'官方资料摘要',platform_guide:'项目训练说明',community_plan:'社区预案',equipment:'设备说明',experience:'复盘经验',reference:'参考资料'}
const scenarios:Record<string,string> = {all:'通用',kitchen_fire:'住宅厨房',charging_shed:'充电棚'}

async function load() {
  const current=++generation; controller?.abort(); controller=new AbortController()
  loading.value=true; error.value=''
  try {
    const params=new URLSearchParams({scenario:scenario.value,page:String(page.value)})
    if(community.value)params.set('community_id',community.value)
    const response=await api.get<{items:KnowledgeDocument[];total:number}>('/knowledge/documents?'+params,{signal:controller.signal})
    if(current!==generation)return
    documents.value=response.items;total.value=response.total
  } catch(cause) { if(current===generation)error.value=cause instanceof Error?cause.message:'资料读取失败。' }
  finally { if(current===generation)loading.value=false }
}
let detailGeneration=0
async function open(documentId:string,sourceVersion?:string) {
  const current=++detailGeneration
  confirmDelete.value=false
  allowEmbedding.value=false
  busy.value=true;error.value='';reviewed.value=false
  try {
    const document=await api.get<KnowledgeDocument>('/knowledge/documents/'+documentId)
    if(disposed||current!==detailGeneration)return
    if(sourceVersion&&!document.versions.some(version=>version.id===sourceVersion))throw new Error('引用的资料版本已不可访问，请核对原检索记录。')
    selected.value=document;versionId.value=document.versions.some(version=>version.id===sourceVersion)?sourceVersion!:document.versions[0]?.id??'';mode.value='detail'
    if(document.community_id&&community.value!==document.community_id)community.value=document.community_id
    if(document.scenario!=='all'&&scenario.value!==document.scenario)scenario.value=document.scenario
  } catch(cause) { if(current===detailGeneration)error.value=cause instanceof Error?cause.message:'资料打开失败。' }
  finally{if(current===detailGeneration)busy.value=false}
}
function create() { form.value=blank();revisionOf.value='';mode.value='new';error.value='';notice.value='' }
function revise() {
  if(!selected.value||!version.value)return
  const d=selected.value
  form.value={title:d.title,content:version.value.text??'',source_url:d.source_url,publisher:d.publisher,category:d.category,filename:'',file_base64:'',valid_date:version.value.valid_until?.slice(0,10)??''}
  revisionOf.value=d.id;community.value=d.community_id??'';scenario.value=d.scenario;mode.value='new';notice.value='修改将保存为新草稿，发布后才替换检索版本。'
}
async function fileChanged(event:Event) {
  const file=(event.target as HTMLInputElement).files?.[0]
  if(!file)return
  if(file.size>3*1024*1024){error.value='文件不能超过 3MB。';return}
  busy.value=true;error.value=''
  try {
    const encoded=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]??'');reader.onerror=()=>reject(new Error('文件读取失败。'));reader.readAsDataURL(file)})
    form.value.file_base64=encoded;form.value.filename=file.name
    if(!form.value.title)form.value.title=file.name.replace(/\.[^.]+$/,'')
  }catch(cause){error.value=cause instanceof Error?cause.message:'文件读取失败。'}finally{busy.value=false}
}
async function save() {
  if(busy.value||voiceBusy.value)return
  busy.value=true;error.value='';notice.value=''
  try {
    const path=revisionOf.value?'/knowledge/documents/'+revisionOf.value+'/versions':'/knowledge/documents'
    const {valid_date,...body}=form.value
    const document=await api.post<KnowledgeDocument>(path,{...body,valid_until:valid_date?new Date(valid_date+'T23:59:59').toISOString():null,content:form.value.file_base64?'':form.value.content,community_id:community.value||null,scenario:scenario.value})
    selected.value=document;versionId.value=document.versions[0]?.id??'';mode.value='detail'
    notice.value=document.versions[0]?.status==='failed'?'提取失败已记录，请修订并重新提交。':'草稿已保存，请核对正文后提交审核。'
    await load()
  }catch(cause){error.value=cause instanceof Error?cause.message:'保存失败。'}finally{busy.value=false}
}
async function act(action:string) {
  if(!selected.value||!version.value||busy.value)return
  busy.value=true;error.value=''
  try {
    selected.value=await api.post<KnowledgeDocument>('/knowledge/documents/'+selected.value.id+'/actions',{action,version_id:version.value.id})
    reviewed.value=false;notice.value=action==='publish'?'已发布，后续检索立即使用该版本。':action==='withdraw'?'已停用，后续检索不再使用该版本。':'已提交审核，请核对来源和适用范围。'
    await load()
  }catch(cause){error.value=cause instanceof Error?cause.message:'状态更新失败。'}finally{busy.value=false}
}
async function search() {
  if(voiceBusy.value)return
  busy.value=true;error.value='';result.value=null
  try { result.value=await api.post<KnowledgeResult>('/knowledge/search',{query:query.value,community_id:community.value||null,scenario:scenario.value,semantic:semantic.value}) }
  catch(cause){error.value=cause instanceof Error?cause.message:'检索失败。'}finally{busy.value=false}
}
async function index() {
  if(!selected.value||!allowEmbedding.value)return
  busy.value=true;error.value=''
  try {const data=await api.post<{indexed_chunks:number}>('/knowledge/documents/'+selected.value.id+'/index');notice.value=`语义索引已建立：${data.indexed_chunks} 个片段。`;await open(selected.value.id)}
  catch(cause){error.value=cause instanceof Error?cause.message:'索引失败。'}finally{busy.value=false}
}
async function remove() {
  if(!selected.value)return
  busy.value=true;error.value=''
  try {await api.delete('/knowledge/documents/'+selected.value.id);selected.value=null;confirmDelete.value=false;notice.value='未发布资料已删除。';await load()}
  catch(cause){error.value=cause instanceof Error?cause.message:'删除失败。'}finally{busy.value=false}
}
watch([community,scenario],()=>{page.value=1;result.value=null;void load()})
watch(page,()=>void load())
watch(versionId,()=>{reviewed.value=false;allowEmbedding.value=false;confirmDelete.value=false})
function replaySource(source:Observation){
  if(source.community_id&&source.scene_id)void router.push({name:'operations',params:{communityId:source.community_id},
    query:{scene:source.scene_id,drill:source.drill_id,mode:'replay',history_at:String(source.observed_at)}})
}
watch([()=>route.query.document,()=>route.query.version],([id,version])=>{
  if(typeof id==='string'&&selected.value?.id!==id)void open(id,typeof version==='string'?version:undefined)
  else if(typeof id==='string'&&typeof version==='string'&&selected.value?.versions.some(item=>item.id===version))versionId.value=version
})
onMounted(async()=>{
  try {
    const [items,status]=await Promise.all([api.get<Array<{id:string;name:string}>>('/communities'),api.get<{embedding_configured:boolean}>('/knowledge/status')])
    communities.value=items;embeddingAvailable.value=status.embedding_configured
    await load()
    if(typeof route.query.document==='string')await open(route.query.document,typeof route.query.version==='string'?route.query.version:undefined)
  }catch(cause){error.value=cause instanceof Error?cause.message:'知识库初始化失败。'}
})
onBeforeUnmount(()=>{disposed=true;generation++;detailGeneration++;controller?.abort()})
</script>

<template>
  <section class="knowledge-center" aria-label="知识与预案">
    <header class="knowledge-center__heading"><div><p>演练知识工作区</p><h1>知识与预案</h1><p>依据有来源，发布有版本；与厨房、充电棚训练共同使用。</p></div><div class="knowledge-center__actions"><button type="button" @click="mode='search';error=''" :disabled="busy"><AppIcon name="search"/>检索资料</button><button type="button" @click="create" :disabled="busy"><AppIcon name="plus"/>添加资料</button></div></header>
    <div class="knowledge-center__filters"><label>使用范围<select v-model="community" :disabled="busy"><option value="">通用与我的未关联资料</option><option v-for="item in communities" :key="item.id" :value="item.id">{{item.name}}</option></select></label><label>适用案例<select v-model="scenario" :disabled="busy"><option v-for="(label,key) in scenarios" :key="key" :value="key">{{key==='all'?'全部案例':label}}</option></select></label><span>{{total}} 份资料 · {{embeddingAvailable?'可选语义检索':'当前使用关键词检索'}}</span></div>
    <p v-if="error" class="knowledge-center__error" role="alert">{{error}} <button type="button" @click="load">重新读取</button></p><p v-if="notice" class="knowledge-center__notice" role="status">{{notice}}</p>
    <div class="knowledge-center__grid">
      <aside class="knowledge-center__catalog" aria-label="资料目录"><h2>资料目录</h2><p v-if="loading" role="status">正在读取资料…</p><p v-else-if="!documents.length">当前范围没有资料，可添加社区预案或切换范围。</p>
        <div class="knowledge-center__list"><button v-for="item in documents" :key="item.id" :aria-pressed="selected?.id===item.id&&mode==='detail'" :disabled="busy" @click="open(item.id)"><span>{{categories[item.category]}} · {{scenarios[item.scenario]}}</span><strong>{{item.title}}</strong><small>{{item.builtin?'内置只读':versionLabel(item.versions[0])}} · V{{item.versions[0]?.number}}</small></button></div>
        <nav v-if="total>30" aria-label="资料分页"><button :disabled="page<=1||busy" @click="page--">上一页</button><span>{{page}} / {{Math.ceil(total/30)}}</span><button :disabled="page*30>=total||busy" @click="page++">下一页</button></nav>
      </aside>
      <div class="knowledge-center__detail">
        <template v-if="mode==='search'"><h2>查找适用依据</h2><SpeechInput :api-base-url="apiBaseUrl" :access-token="accessToken" tone="light" destination="检索框" :disabled="busy" @activity="value=>voiceBusy=value" @transcript="text=>query=text.slice(0,2000)"/><form @submit.prevent="search"><label>问题或关键词<textarea v-model="query" maxlength="2000" rows="3" required placeholder="例如：厨房房门何时能关闭？重点居民怎样安排护送？"/></label><label v-if="embeddingAvailable" class="knowledge-center__check"><input v-model="semantic" type="checkbox"/>授权将本次检索问题发送给配置的 Embedding 服务</label><button :disabled="busy||voiceBusy||query.trim().length<2" type="submit">{{busy?'检索中…':'检索发布资料'}}</button></form><KnowledgeEvidence v-if="result" :result="result" @open="source=>open(source.documentId,source.versionId)"/><p v-if="!result">只检索当前权限范围内已发布且适用的版本。现场人数、道路和任务进度以导演台服务端状态为准。</p></template>
        <template v-else-if="mode==='new'"><h2>{{revisionOf?'保存新版本':'添加专属资料'}}</h2><form @submit.prevent="save">
          <label>资料名称<input v-model="form.title" minlength="2" maxlength="200" required :disabled="!!revisionOf"/></label>
          <div class="knowledge-center__fields"><label>资料类别<select v-model="form.category" :disabled="!!revisionOf"><option value="community_plan">社区预案</option><option value="equipment">设备说明</option><option value="experience">复盘经验</option><option value="reference">参考资料</option></select></label><label>来源机构或编写人<input v-model="form.publisher" maxlength="200" :disabled="!!revisionOf"/></label></div>
          <label>原始来源链接（可选）<input v-model="form.source_url" type="url" placeholder="https://…" maxlength="1200" :disabled="!!revisionOf"/></label>
          <label>有效截止日期（可选）<input v-model="form.valid_date" type="date"/></label>
          <label>上传资料<input type="file" accept=".txt,.md,.docx,.pdf" :disabled="busy" @change="fileChanged"/></label><p>支持文本型 PDF、DOCX、Markdown、UTF-8 文本，最大 3MB。扫描件需先识别。{{form.filename?'已选择：'+form.filename:''}}</p>
          <button v-if="form.file_base64" type="button" @click="form.file_base64='';form.filename=''">取消文件，使用下方正文</button>
          <SpeechInput v-if="form.category==='experience'&&!form.file_base64" :api-base-url="apiBaseUrl" :access-token="accessToken" tone="light" destination="经验正文" :disabled="busy" @activity="value=>voiceBusy=value" @transcript="text=>form.content=(form.content.trimEnd()+'\n'+text).slice(0,80000)"/><label>资料正文<textarea v-model="form.content" :disabled="!!form.file_base64" rows="10" maxlength="80000" placeholder="粘贴社区预案、设备说明或经过审核的复盘经验。"/></label>
          <button type="submit" :disabled="busy||voiceBusy">{{busy?'正在提取并保存…':'保存草稿'}}</button>
        </form></template>
        <template v-else-if="selected&&version"><div class="knowledge-center__document-heading"><div><p>{{categories[selected.category]}} · {{scenarios[selected.scenario]}}</p><h2>{{selected.title}}</h2></div><select v-model="versionId" aria-label="资料版本"><option v-for="v in selected.versions" :key="v.id" :value="v.id">V{{v.number}} · {{versionLabel(v)}}</option></select></div>
          <p>{{selected.publisher||'用户资料'}} <span>· {{versionLabel(version)}}</span></p><p v-if="selected.source_url"><a :href="selected.source_url" target="_blank" rel="noopener noreferrer">打开来源网站<AppIcon name="arrowRight" :size="16"/></a></p>
          <KnowledgeObservation v-if="selected.experience" :source="selected.experience" @replay="replaySource"/><p v-else-if="selected.category==='experience'">这份经验为人工编写，未关联系统生成的观察记录。</p><p v-if="selected.category==='official_summary'" class="knowledge-center__notice">这里展示经整理的资料摘要；完整内容以来源网站为准。</p>
          <p v-if="version.failure" class="knowledge-center__error" role="alert">{{version.failure}}</p>
          <div v-if="!selected.builtin" class="knowledge-center__actions"><button v-if="version.status==='draft'" :disabled="busy" @click="act('review')">提交审核</button><button :disabled="busy" @click="revise">修订为新草稿</button><button v-if="version.status==='published'" :disabled="busy" @click="act('withdraw')">停用当前版本</button></div>
          <div v-if="!selected.builtin&&version.status==='review'" class="knowledge-center__review"><label class="knowledge-center__check"><input v-model="reviewed" type="checkbox"/>{{selected.experience?'已核对观察事实、适用条件与正文结论':'已核对正文、来源与适用范围'}}</label><button :disabled="busy||!reviewed" @click="act('publish')">确认审核并发布</button></div>
          <p v-if="version.reviewer">发布审核：{{version.reviewer}} · {{version.reviewed_at?new Date(version.reviewed_at).toLocaleString('zh-CN'):''}}</p>
          <p>{{version.valid_until?'有效期至：'+new Date(version.valid_until).toLocaleString('zh-CN'):'未设置有效截止时间；适用性仍需结合来源核对。'}}</p>
          <template v-if="!selected.builtin&&selected.versions.every(v=>['draft','review','failed'].includes(v.status))"><button :disabled="busy" @click="confirmDelete=!confirmDelete">删除未发布资料</button><div v-if="confirmDelete" class="knowledge-center__review"><p>确认删除这份未发布资料及其草稿？</p><button :disabled="busy" @click="remove">确认删除</button><button @click="confirmDelete=false">保留资料</button></div></template>
          <details v-if="embeddingAvailable&&version.status==='published'"><summary>语义索引设置</summary><label class="knowledge-center__check"><input v-model="allowEmbedding" type="checkbox"/>授权将此版本资料发送至配置的 Embedding 服务</label><button :disabled="busy||!allowEmbedding" @click="index">建立语义索引</button><p>{{version.embedding_model?'当前索引：'+version.embedding_model:'尚未建立语义索引，关键词检索可用。'}}</p></details>
          <div class="knowledge-center__content"><p v-if="!version.chunks?.length">此版本没有有效正文，请修订资料。</p><article v-for="chunk in version.chunks" :key="chunk.id"><h3>{{chunk.anchor}}</h3><p>{{chunk.content}}</p><small>内容校验 {{chunk.content_hash.slice(0,12)}}</small></article></div>
        </template>
        <div v-else class="knowledge-center__empty"><AppIcon name="book" :size="40"/><h2>把依据带进演练</h2><p>选择左侧资料核对来源与适用范围，或检索厨房烟气、充电风险和重点人员准备。发布后的社区预案会出现在对应场次助手的检索依据中。</p><button @click="mode='search'">开始检索</button></div>
      </div>
    </div>
  </section>
</template>
