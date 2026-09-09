import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router'
import './styles/tokens.css'
import './styles.css'
import './styles/base.css'
import './styles/components.css'
import './styles/responsive.css'

const legacyInvite = location.hash.match(/^#\/participant\/([^?]+)\?code=([^&]+)/)
if (legacyInvite) history.replaceState(null, '', `/participant/${legacyInvite[1]}?code=${legacyInvite[2]}`)
const app = createApp(App).use(router)
void router.isReady().then(() => app.mount('#app'))
