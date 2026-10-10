<script setup>
defineProps({ name: { type: String, default: 'shield' } });
const paths = {
 home: ['M3 10l9-7 9 7', 'M5 9v12h14V9', 'M9 21v-8h6v8'],
 shield: ['M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6z', 'M8 12l3 3 5-6'],
 user: ['M20 21v-2a7 7 0 0 0-14 0v2', 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8'],
 ticket: ['M3 6h18v4a2 2 0 0 0 0 4v4H3v-4a2 2 0 0 0 0-4z', 'M14 6v3m0 3v2m0 3v1'],
 arrow: ['M5 12h14', 'M13 6l6 6-6 6'],
 plus: ['M12 5v14', 'M5 12h14'],
 refresh: ['M20 7v5h-5', 'M4 17v-5h5', 'M6 6a8 8 0 0 1 13 1', 'M18 18A8 8 0 0 1 5 17'],
 search: ['M21 21l-5-5', 'M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14'],
 clock: ['M12 8v5l3 2', 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20'],
 check: ['M5 12l4 4L19 6'],
 alert: ['M12 3L2 21h20z', 'M12 9v4', 'M12 17v.1'],
 lock: ['M5 10h14v11H5z', 'M8 10V7a4 4 0 0 1 8 0v3', 'M12 14v3'],
 copy: ['M9 9h12v12H9z', 'M15 9V3H3v12h6'],
 court: ['M4 3h16v18H4z', 'M4 12h16', 'M8 3v18', 'M16 3v18', 'M4 8h16', 'M4 16h16'],
 settings: ['M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8', 'M4.9 4.9l1.4 1.4', 'M17.7 17.7l1.4 1.4', 'M3 12h2', 'M19 12h2', 'M4.9 19.1l1.4-1.4', 'M17.7 6.3l1.4-1.4', 'M12 3v2', 'M12 19v2'],
};
</script>
<template><svg class="app-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path v-for="(path,index) in (paths[name] || paths.shield)" :key="index" :d="path" /></svg></template>
