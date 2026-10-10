<script setup>
defineProps({ answers: { type: Array, default: () => [] }, questions: { type: Array, default: () => [] },
  history: { type: Array, default: () => [] }, answer: { type: String, default: '' }, busy: Boolean, blocked: Boolean });
defineEmits(['update:answer', 'continue']);
</script>

<template>
  <section class="follow-up" aria-label="补充对话">
    <ol v-if="answers.length" class="answer-history"><li v-for="(item,index) in answers" :key="index"><span v-if="history[index]?.length" class="previous-question">追问：{{ history[index].join('；') }}</span><strong>补充 {{ index+1 }}</strong>：{{ item }}</li></ol>
    <template v-if="questions.length">
      <h3>还需要补充信息</h3>
      <ul><li v-for="(question,index) in questions" :key="index">{{ question }}</li></ul>
      <p class="muted">直接回答下面的问题即可。原始描述与已提交的补充内容会一起理解。</p>
      <label class="field">补充回答<textarea data-testid="proposal-answer" :value="answer" rows="2" maxlength="4000" :disabled="busy||blocked" @input="$emit('update:answer',$event.target.value)" /></label>
      <button class="primary-button" data-testid="continue-proposal" type="button" :disabled="busy||blocked||!answer.trim()||answers.length>=7" @click="$emit('continue')">{{ busy?'正在继续…':'继续生成' }}</button>
      <p v-if="answers.length>=7" class="muted">已达到 7 次补充上限，请重新开始。</p>
    </template>
  </section>
</template>

<style scoped>
.follow-up{display:grid;gap:12px;padding:18px;background:var(--brand-soft);border-radius:12px}.follow-up h3,.follow-up p{margin:0}.answer-history{padding-left:22px;margin:0;overflow-wrap:anywhere}.previous-question{display:block;color:var(--muted)}.answer-history li{margin:6px 0}.field textarea{width:100%;box-sizing:border-box;font:inherit;resize:vertical;padding:12px;border:1px solid var(--line);border-radius:9px;background:var(--surface);color:var(--ink)}.primary-button{justify-self:start}
</style>
