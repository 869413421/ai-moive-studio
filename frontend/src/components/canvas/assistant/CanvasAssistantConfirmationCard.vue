<template>
  <article class="assistant-confirmation">
    <div class="assistant-confirmation__header">
      <div>
        <div class="assistant-confirmation__eyebrow">{{ interrupt.kind || 'interrupt' }}</div>
        <h3 class="assistant-confirmation__title">{{ interrupt.title || '请确认' }}</h3>
      </div>
      <span class="assistant-confirmation__badge">待确认</span>
    </div>

    <p v-if="interrupt.message" class="assistant-confirmation__message">
      {{ interrupt.message }}
    </p>

    <div v-if="interrupt.modelOptions.length" class="assistant-confirmation__section">
      <label class="assistant-confirmation__label" for="assistant-model-select">执行模型</label>
      <select
        id="assistant-model-select"
        class="assistant-confirmation__select"
        :disabled="busy"
        :value="draftSelectedModelId"
        @change="handleModelChange"
      >
        <option value="">保持默认</option>
        <option
          v-for="option in interrupt.modelOptions"
          :key="option.modelId || option.label"
          :value="option.modelId"
        >
          {{ option.label || option.modelName || option.modelId }}{{ option.resolution ? ` · ${option.resolution}` : '' }}
        </option>
      </select>
    </div>

    <details v-if="interrupt.actions.length" class="assistant-confirmation__details">
      <summary>查看可用动作</summary>
      <pre>{{ formatJson(interrupt.actions) }}</pre>
    </details>

    <div class="assistant-confirmation__actions">
      <button class="assistant-confirmation__button assistant-confirmation__button--ghost" type="button" :disabled="busy" @click="$emit('reject')">
        拒绝
      </button>
      <button class="assistant-confirmation__button assistant-confirmation__button--primary" type="button" :disabled="busy" @click="$emit('approve', draftSelectedModelId)">
        {{ busy ? '处理中' : '确认执行' }}
      </button>
    </div>
  </article>
</template>

<script setup>
  import { computed, ref, watch } from 'vue'

  const props = defineProps({
    interrupt: {
      type: Object,
      default: () => ({
        interruptId: '',
        title: '',
        message: '',
        selectedModelId: '',
        modelOptions: [],
        actions: []
      })
    },
    // selectedModelId: 外层当前保存的模型选择值。
    selectedModelId: { type: String, default: '' },
    // busy: 确认或拒绝提交中时禁用交互。
    busy: { type: Boolean, default: false }
  })

  const emit = defineEmits(['approve', 'reject', 'update:selected-model-id'])

  const draftSelectedModelId = ref('')
  const interrupt = computed(() => props.interrupt || {})

  // 组件内部保留一份可编辑模型草稿，避免直接修改父层状态。
  const resolvedSelectedModelId = computed(() =>
    String(props.selectedModelId || interrupt.value?.selectedModelId || '').trim()
  )

  watch(
    resolvedSelectedModelId,
    (value) => {
      draftSelectedModelId.value = value
    },
    { immediate: true }
  )

  const handleModelChange = (event) => {
    draftSelectedModelId.value = String(event.target.value || '').trim()
    emit('update:selected-model-id', draftSelectedModelId.value)
  }

  const formatJson = (value) => {
    // 计划快照主要用于学习和调试，所以这里保留可读的格式化输出。
    try {
      return JSON.stringify(value, null, 2)
    } catch {
      return String(value || '')
    }
  }
</script>

<style scoped>
  .assistant-confirmation {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 16px;
    border-radius: 20px;
    border: 1px solid rgba(75, 120, 255, 0.14);
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(242, 247, 255, 0.96));
    box-shadow: 0 14px 28px rgba(75, 120, 255, 0.08);
  }

  .assistant-confirmation__header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
  }

  .assistant-confirmation__eyebrow {
    color: #6a768f;
    font-size: 11px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
  }

  .assistant-confirmation__title {
    margin: 4px 0 0;
    color: #1f2a44;
    font-size: 16px;
    line-height: 1.35;
  }

  .assistant-confirmation__badge {
    padding: 6px 10px;
    border-radius: 999px;
    background: #e7efff;
    color: #355ce0;
    font-size: 12px;
    font-weight: 600;
    white-space: nowrap;
  }

  .assistant-confirmation__message {
    margin: 0;
    color: #52607a;
    font-size: 13px;
    line-height: 1.6;
  }

  .assistant-confirmation__section {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .assistant-confirmation__label {
    color: #6a768f;
    font-size: 12px;
    font-weight: 600;
  }
  .assistant-confirmation__select {
    width: 100%;
    min-height: 40px;
    border-radius: 14px;
    border: 1px solid rgba(34, 57, 98, 0.12);
    background: #fff;
    padding: 0 12px;
    color: #1f2a44;
    font: inherit;
  }

  .assistant-confirmation__details {
    color: #52607a;
    font-size: 12px;
  }

  .assistant-confirmation__details summary {
    cursor: pointer;
    color: #355ce0;
    margin-bottom: 8px;
  }

  .assistant-confirmation__details pre {
    margin: 0;
    padding: 12px;
    overflow: auto;
    border-radius: 14px;
    background: rgba(34, 57, 98, 0.04);
    white-space: pre-wrap;
  }

  .assistant-confirmation__actions {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    flex-wrap: wrap;
  }

  .assistant-confirmation__button {
    padding: 10px 14px;
    border-radius: 999px;
    border: 1px solid transparent;
    cursor: pointer;
    font-weight: 600;
  }

  .assistant-confirmation__button--ghost {
    background: #fff;
    color: #52607a;
    border-color: rgba(34, 57, 98, 0.12);
  }

  .assistant-confirmation__button--primary {
    background: linear-gradient(180deg, #4b78ff, #355ce0);
    color: #fff;
  }

  .assistant-confirmation__button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
