<template>
  <article class="assistant-message" :class="[`assistant-message--${messageRole}`, `assistant-message--${tone}`]">
    <div class="assistant-message__meta">
      <span class="assistant-message__role">{{ roleLabel }}</span>
      <span v-if="message.order !== undefined" class="assistant-message__order">#{{ message.order }}</span>
    </div>
    <div class="assistant-message__content">
      {{ message.content || '（空消息）' }}
      <span
        v-if="streaming && messageRole === 'assistant'"
        class="assistant-message__cursor"
      ></span>
    </div>
  </article>
</template>

<script setup>
  import { computed } from 'vue'

  const props = defineProps({
    // message: 标准化后的时间线消息对象。
    message: {
      type: Object,
      default: () => ({ role: 'assistant', content: '' })
    },
    // tone: 额外语气标记，当前主要用于错误态。
    tone: {
      type: String,
      default: 'default'
    },
    streaming: {
      type: Boolean,
      default: false
    }
  })

  const messageRole = computed(() =>
    String(props.message?.role || 'assistant').trim() === 'user' ? 'user' : 'assistant'
  )

  const roleLabel = computed(() => {
    if (props.tone === 'error') return '错误'
    return messageRole.value === 'user' ? '你' : '助手'
  })
</script>

<style scoped>
  .assistant-message {
    padding: 14px 16px;
    border-radius: 18px;
    border: 1px solid rgba(34, 57, 98, 0.08);
    box-shadow: 0 10px 24px rgba(34, 57, 98, 0.06);
  }

  .assistant-message--assistant {
    align-self: flex-start;
    background: rgba(255, 255, 255, 0.96);
  }

  .assistant-message--user {
    align-self: flex-end;
    background: linear-gradient(180deg, #4b78ff, #355ce0);
    color: #fff;
  }

  .assistant-message--error {
    background: rgba(252, 232, 230, 0.96);
    border-color: rgba(180, 35, 24, 0.16);
  }

  .assistant-message__meta {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    margin-bottom: 8px;
    font-size: 11px;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  .assistant-message__role,
  .assistant-message__order {
    color: inherit;
    opacity: 0.72;
  }

  .assistant-message__content {
    white-space: pre-wrap;
    word-break: break-word;
    line-height: 1.65;
    font-size: 14px;
    color: inherit;
    user-select: text;
    -webkit-user-select: text;
  }

  .assistant-message__cursor {
    display: inline-block;
    width: 8px;
    height: 1em;
    margin-left: 2px;
    vertical-align: text-bottom;
    border-right: 2px solid currentColor;
    animation: assistant-message-cursor 0.9s step-end infinite;
  }

  @keyframes assistant-message-cursor {
    0%,
    45% {
      opacity: 1;
    }
    46%,
    100% {
      opacity: 0;
    }
  }
</style>
