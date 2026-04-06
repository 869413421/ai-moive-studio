<template>
  <header class="assistant-header">
    <div class="assistant-header__copy">
      <div class="assistant-header__eyebrow">Canvas assistant</div>
      <h2 class="assistant-header__title">{{ title }}</h2>
      <p class="assistant-header__subtitle">
        {{ subtitle }}
      </p>
    </div>

    <div class="assistant-header__actions">
      <span class="assistant-status" :class="`assistant-status--${statusTone}`">
        {{ statusLabel }}
      </span>
      <button v-if="canReset" class="assistant-header__reset" type="button" @click="$emit('reset')">
        重置会话
      </button>
    </div>

    <div v-if="sessionId" class="assistant-header__chips">
      <span v-if="sessionId" class="assistant-chip">Session {{ sessionId }}</span>
    </div>
  </header>
</template>

<script setup>
  import { computed } from 'vue'

  const props = defineProps({
    // title: 助手栏标题。
    title: { type: String, default: 'AI 助手' },
    // status: assistant 当前状态，例如 idle / streaming / awaiting_confirmation。
    status: { type: String, default: 'idle' },
    // sessionId: 当前会话 id，便于调试和学习确认恢复链路。
    sessionId: { type: String, default: '' },
    // canReset: 是否展示“重置会话”按钮。
    canReset: { type: Boolean, default: false },
    // streaming: 当前是否正在流式处理。
    streaming: { type: Boolean, default: false }
  })

  defineEmits(['reset'])

  const statusLabels = {
    idle: '待命',
    streaming: '处理中',
    awaiting_interrupt: '等待确认',
    error: '发生错误'
  }

  const statusTone = computed(() => {
    if (props.status === 'streaming') return 'busy'
    if (props.status === 'awaiting_interrupt') return 'warning'
    if (props.status === 'error') return 'error'
    return 'idle'
  })

  const statusLabel = computed(() => statusLabels[props.status] || '待命')

  const subtitle = computed(() => {
    // 头部副文案不讲“产品废话”，只解释当前这一刻助手在做什么。
    if (props.streaming) {
      return '正在编排当前链路，请在下方查看实时进展。'
    }

    if (props.status === 'awaiting_interrupt') {
      return '助手已经给出确认卡，先选模型再继续。'
    }

    return '直接描述你想要的改动，Agent 会自行观察并定位画布目标。'
  })
</script>

<style scoped>
  .assistant-header {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 18px 18px 16px;
    border-radius: 22px;
    border: 1px solid rgba(34, 57, 98, 0.08);
    background: rgba(255, 255, 255, 0.9);
    box-shadow: 0 14px 32px rgba(34, 57, 98, 0.08);
  }

  .assistant-header__copy {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .assistant-header__eyebrow {
    color: #6a768f;
    font-size: 11px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
  }

  .assistant-header__title {
    margin: 0;
    color: #1f2a44;
    font-size: 20px;
    line-height: 1.2;
  }

  .assistant-header__subtitle {
    margin: 0;
    color: #5f6b85;
    font-size: 13px;
    line-height: 1.5;
  }

  .assistant-header__actions,
  .assistant-header__chips {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }

  .assistant-header__actions {
    justify-content: space-between;
  }

  .assistant-status,
  .assistant-chip,
  .assistant-header__reset {
    border-radius: 999px;
    font-size: 12px;
  }

  .assistant-status {
    padding: 7px 11px;
    font-weight: 600;
  }

  .assistant-status--idle {
    color: #52607a;
    background: #edf2f8;
  }

  .assistant-status--busy {
    color: #1855d6;
    background: #e7efff;
  }

  .assistant-status--warning {
    color: #ad6500;
    background: #fff2d8;
  }

  .assistant-status--error {
    color: #b42318;
    background: #fce8e6;
  }

  .assistant-header__reset {
    border: 1px solid rgba(34, 57, 98, 0.08);
    background: #fff;
    color: #52607a;
    padding: 7px 12px;
    cursor: pointer;
  }

  .assistant-header__reset:hover {
    color: #1f2a44;
    background: #f8fbff;
  }

  .assistant-chip {
    padding: 6px 10px;
    background: rgba(75, 120, 255, 0.08);
    color: #355ce0;
    border: 1px solid rgba(75, 120, 255, 0.12);
  }

</style>
