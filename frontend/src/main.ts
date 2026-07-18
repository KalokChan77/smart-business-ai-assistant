import { createApp } from "vue";

import App from "@/App.vue";
import { onAuthExpired } from "@/api/client";
import router from "@/router";
import { pinia } from "@/stores";
import { useAuthStore } from "@/stores/auth";
import "@/styles/global.css";

const app = createApp(App);
app.use(pinia);

const auth = useAuthStore(pinia);
onAuthExpired(() => auth.clear());
await auth.restore();

app.use(router);
await router.isReady();
app.mount("#app");
