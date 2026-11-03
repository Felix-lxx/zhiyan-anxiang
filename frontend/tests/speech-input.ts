import { createApp, h, ref } from 'vue'
import SceneAssistant from '../src/components/SceneAssistant.vue'
import '../src/styles/tokens.css'
import '../src/styles/base.css'
import '../src/styles/components.css'
const open = ref(true)
createApp({ setup: () => () => h('main', { style: 'min-height:100dvh;background:#0a2921', 'data-ui-theme': 'immersive' }, [
  h('button', { onClick: () => { open.value = true } }, '打开助手'),
  h(SceneAssistant, { apiBaseUrl: location.origin + '/speech-fixture', accessToken: 'isolated-test',
    drillId: 'speech-fixture', drillName: '语音测试场次', open: open.value, atSeconds: null, liveSeconds: 0,
    drillStatus: 'ready', onClose: () => { open.value = false } }),
]) }).mount('#app')
