<script setup>
import { onMounted, onUnmounted, ref } from 'vue';
import AppIcon from './AppIcon.vue';
import { applyThemePreference, readThemePreference, THEME_CHOICES, THEME_STORAGE_KEY } from '../utils/theme.js';

const menu = ref(null);
const preference = ref(applyThemePreference(readThemePreference()));
function choose(value) {
  preference.value = applyThemePreference(value, { persist: true });
  if (menu.value) menu.value.open = false;
  menu.value?.querySelector('summary')?.focus();
}
function storageChanged(event) {
  if (event.key === THEME_STORAGE_KEY || event.key === null) preference.value = applyThemePreference(readThemePreference());
}
function close() { if (menu.value) { menu.value.open = false; menu.value.querySelector('summary')?.focus(); } }
onMounted(() => window.addEventListener('storage', storageChanged));
onUnmounted(() => window.removeEventListener('storage', storageChanged));
</script>

<template>
  <details ref="menu" class="theme-switcher" name="workspace-navigation" @keydown.esc.prevent="close">
    <summary aria-label="切换外观" title="切换外观"><AppIcon :name="preference === 'dark' ? 'moon' : preference === 'light' ? 'sun' : 'display'" /><span class="sr-only">外观</span></summary>
    <fieldset class="theme-menu">
      <legend>外观</legend>
      <label v-for="choice in THEME_CHOICES" :key="choice.value" :class="{'is-selected':preference === choice.value}">
        <input type="radio" name="appearance" :value="choice.value" :checked="preference === choice.value" @change="choose(choice.value)" />
        <span>{{ choice.label }}</span><AppIcon v-if="preference === choice.value" name="check" />
      </label>
    </fieldset>
  </details>
</template>

<style scoped>
.theme-switcher{position:relative;flex:none;order:1}
.theme-switcher>summary{display:grid;place-items:center;width:44px;min-height:44px;border-radius:50%;color:var(--muted);cursor:pointer;list-style:none}
.theme-switcher>summary::-webkit-details-marker{display:none}
.theme-switcher>summary:hover{color:var(--ink);background:var(--apple-hover)}
.theme-menu{position:absolute;right:0;top:calc(100% + 8px);z-index:60;min-width:164px;margin:0;padding:8px;border:1px solid var(--line);border-radius:16px;background:var(--surface);box-shadow:var(--apple-popover-shadow)}
.theme-menu legend{float:left;width:100%;padding:4px 8px;color:var(--muted);font-size:12px}
.theme-menu label{position:relative;clear:both;display:flex;align-items:center;gap:8px;min-height:44px;padding:8px;border-radius:10px;color:var(--ink);font-size:13px;cursor:pointer}
.theme-menu label:hover,.theme-menu label.is-selected{background:var(--brand-soft)}
.theme-menu input{width:16px;height:16px;margin:0;accent-color:var(--action)}
.theme-menu .app-icon{width:16px;height:16px;margin-left:auto;color:var(--brand)}
</style>
