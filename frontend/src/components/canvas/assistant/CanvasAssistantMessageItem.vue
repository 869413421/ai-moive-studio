<template>
  <article class="assistant-message" :class="[`assistant-message--${messageRole}`, `assistant-message--${tone}`]">
    <div class="assistant-message__meta">
      <span class="assistant-message__role">{{ roleLabel }}</span>
      <span v-if="message.order !== undefined" class="assistant-message__order">#{{ message.order }}</span>
    </div>
    <div class="assistant-message__content">
      {{ displayedContent || contentFallback }}
      <span
        v-if="showCursor"
        class="assistant-message__cursor"
      ></span>
      <span v-if="showWave" class="assistant-message__wave" aria-hidden="true">
        <span></span><span></span><span></span><span></span>
      </span>
    </div>
  </article>
</template>

<script setup>
  import { computed, onBeforeUnmount, ref, watch } from 'vue'

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
    },
    live: {
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

  const displayedContent = ref('')
  const queuedContent = ref('')
  const animating = ref(false)
  let typingFrameId = null
  let finalizeTimerId = null

  const showCursor = computed(() => messageRole.value === 'assistant' && (props.streaming || animating.value))
  const showWave = computed(() => messageRole.value === 'assistant' && props.live)
  const contentFallback = computed(() =>
    messageRole.value === 'assistant' && props.live ? '' : '（空消息）'
  )

  const stopTypingLoop = () => {
    if (typingFrameId) {
      window.cancelAnimationFrame(typingFrameId)
      typingFrameId = null
    }
  }

  const clearFinalizeTimer = () => {
    if (finalizeTimerId) {
      window.clearTimeout(finalizeTimerId)
      finalizeTimerId = null
    }
  }

  const startTypingLoop = () => {
    if (typingFrameId || messageRole.value !== 'assistant') {
      return
    }
    animating.value = true

    const loop = () => {
      const target = String(queuedContent.value || '')
      if (messageRole.value !== 'assistant') {
        displayedContent.value = target
        animating.value = false
        typingFrameId = null
        return
      }
      if (!target.startsWith(displayedContent.value)) {
        displayedContent.value = ''
      }
      if (displayedContent.value.length < target.length) {
        const gap = target.length - displayedContent.value.length
        const step = Math.max(1, Math.min(4, Math.floor(gap / 8) || 1))
        displayedContent.value = target.slice(0, displayedContent.value.length + step)
        typingFrameId = window.requestAnimationFrame(loop)
        return
      }
      clearFinalizeTimer()
      finalizeTimerId = window.setTimeout(() => {
        animating.value = false
        finalizeTimerId = null
      }, props.streaming ? 0 : 320)
      typingFrameId = null
    }

    typingFrameId = window.requestAnimationFrame(loop)
  }

  const syncDisplayedContent = (nextContent) => {
    const normalized = String(nextContent || '')
    if (messageRole.value !== 'assistant') {
      queuedContent.value = normalized
      displayedContent.value = normalized
      animating.value = false
      return
    }
    if (!normalized.startsWith(queuedContent.value || displayedContent.value)) {
      displayedContent.value = ''
      queuedContent.value = normalized
    } else {
      queuedContent.value = normalized
    }
    startTypingLoop()
  }

  watch(
    () => [props.message?.content, props.streaming, messageRole.value],
    ([nextContent]) => {
      stopTypingLoop()
      clearFinalizeTimer()
      syncDisplayedContent(nextContent)
    },
    { immediate: true }
  )

  onBeforeUnmount(() => {
    stopTypingLoop()
    clearFinalizeTimer()
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
    width: 10px;
    height: 1em;
    margin-left: 4px;
    vertical-align: text-bottom;
    border-right: 2px solid currentColor;
    filter: drop-shadow(0 0 6px currentColor);
    animation: assistant-message-cursor 0.82s step-end infinite;
  }

  .assistant-message__wave {
    display: inline-flex;
    align-items: flex-end;
    gap: 3px;
    margin-left: 8px;
    vertical-align: middle;
    height: 12px;
  }

  .assistant-message__wave span {
    display: inline-block;
    width: 3px;
    border-radius: 999px;
    background: currentColor;
    opacity: 0.75;
    transform-origin: center bottom;
    animation: assistant-message-wave 1.2s ease-in-out infinite;
  }

  .assistant-message__wave span:nth-child(1) {
    height: 5px;
    animation-delay: -0.45s;
  }

  .assistant-message__wave span:nth-child(2) {
    height: 9px;
    animation-delay: -0.3s;
  }

  .assistant-message__wave span:nth-child(3) {
    height: 12px;
    animation-delay: -0.15s;
  }

  .assistant-message__wave span:nth-child(4) {
    height: 7px;
    animation-delay: 0s;
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

  @keyframes assistant-message-wave {
    0%, 100% {
      transform: scaleY(0.55);
      opacity: 0.42;
    }
    50% {
      transform: scaleY(1);
      opacity: 1;
      filter: drop-shadow(0 0 4px currentColor);
    }
  }
</style>
