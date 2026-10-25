export const THEME_STORAGE_KEY = 'yumao-theme';
export const THEME_CHOICES = [
  { value: 'system', label: '跟随系统' },
  { value: 'light', label: '浅色' },
  { value: 'dark', label: '深色' },
];
export const normalizeTheme = value => THEME_CHOICES.some(choice => choice.value === value) ? value : 'system';

export function readThemePreference() {
  try { return normalizeTheme(window.localStorage.getItem(THEME_STORAGE_KEY)); }
  catch { return 'system'; }
}

export function applyThemePreference(value, { persist = false } = {}) {
  const preference = normalizeTheme(value);
  document.documentElement.dataset.theme = preference;
  // Browser chrome must follow the explicit choice as well as CSS/native controls.
  for (const meta of document.querySelectorAll('meta[name="theme-color"]')) {
    const dark = preference === 'dark' || (preference === 'system' && (meta.getAttribute('media') || '').includes('dark'));
    meta.content = dark ? '#000000' : '#f5f5f7';
  }
  if (persist) {
    try {
      if (preference === 'system') window.localStorage.removeItem(THEME_STORAGE_KEY);
      else window.localStorage.setItem(THEME_STORAGE_KEY, preference);
    } catch { /* The choice still works when browser storage is unavailable. */ }
  }
  return preference;
}
