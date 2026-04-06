<template>
  <div class="assistant-timeline">
    <div ref="scrollRef" class="assistant-timeline__scroll">
      <div v-if="!items.length" class="assistant-timeline__empty">
        <div class="assistant-timeline__empty-title">从一句话开始</div>
        <div class="assistant-timeline__empty-hint">
          直接说目标，Agent 会自己观察画布、推理下一步并执行动作。
        </div>
      </div>

      <div v-if="items.length" class="assistant-timeline__list">
        <template v-for="item in conversationItems" :key="item.id">
          <CanvasAssistantMessageItem
            v-if="item.type === 'user_message' || item.type === 'assistant_message'"
            :message="item.message"
            :streaming="busy && item.type === 'assistant_message'"
          />
          <CanvasAssistantMessageItem
            v-else-if="item.type === 'error_notice'"
            :message="{ role: 'assistant', content: item.message }"
            tone="error"
          />
          <CanvasAssistantConfirmationCard
            v-else-if="item.type === 'interrupt_card'"
            :interrupt="item.interrupt"
            :busy="busy"
            @approve="emit('approve', $event)"
            @reject="emit('reject')"
            @update:selected-model-id="emit('update:selected-model-id', $event)"
          />
        </template>
      </div>

      <div v-if="activitySummary" class="assistant-timeline__activity">
        <CanvasAssistantToolSummary
          :thinking-buffer="activitySummary.thinkingBuffer"
          :tool-calls="activitySummary.toolCalls"
          :live="busy"
        />
      </div>

      <div v-if="showLoading" class="assistant-timeline__loading">
        <div class="assistant-timeline__loading-ring"></div>
        <div class="assistant-dot-pulse">
          <span></span><span></span><span></span>
        </div>
        <div class="assistant-timeline__loading-label">正在继续处理当前工作流</div>
      </div>
    </div>
  </div>
</template>

<script setup>
  import { computed, nextTick, ref, watch } from 'vue'
  import CanvasAssistantConfirmationCard from './CanvasAssistantConfirmationCard.vue'
  import CanvasAssistantMessageItem from './CanvasAssistantMessageItem.vue'
  import CanvasAssistantToolSummary from './CanvasAssistantToolSummary.vue'

  const props = defineProps({
    // items: 时间线派生后的统一渲染项。
    items: { type: Array, default: () => [] },
    // busy: 当前是否正在流式处理或提交确认。
    busy: { type: Boolean, default: false }
  })

  const emit = defineEmits(['approve', 'reject', 'update:selected-model-id'])
  const scrollRef = ref(null)
  const conversationItems = computed(() =>
    (Array.isArray(props.items) ? props.items : []).filter((item) => item?.type !== 'tool_summary')
  )
  const activitySummary = computed(() => {
    const summaries = (Array.isArray(props.items) ? props.items : []).filter((item) => item?.type === 'tool_summary')
    return summaries.length ? summaries[summaries.length - 1] : null
  })
  const showLoading = computed(() => {
    if (props.busy) return true
    const toolCalls = Array.isArray(activitySummary.value?.toolCalls) ? activitySummary.value.toolCalls : []
    return toolCalls.some((toolCall) => !['completed', 'failed'].includes(String(toolCall?.status || '').trim()))
  })

  watch(
    () => [props.items, props.busy],
    async () => {
      await nextTick()
      scrollRef.value?.scrollTo?.({
        top: scrollRef.value.scrollHeight,
        behavior: 'smooth'
      })
    },
    { deep: true }
  )
</script>

<style scoped>
  .assistant-timeline {
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  .assistant-timeline__empty,
  .assistant-timeline__scroll {
    min-height: 0;
    overflow: auto;
  }

  .assistant-timeline__scroll {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding-right: 6px;
  }

  .assistant-timeline__empty {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 6px;
    padding: 26px 18px;
    border-radius: 22px;
    border: 1px dashed rgba(34, 57, 98, 0.14);
    background: rgba(255, 255, 255, 0.68);
  }

  .assistant-timeline__empty-title {
    color: #1f2a44;
    font-size: 15px;
    font-weight: 600;
  }

  .assistant-timeline__empty-hint {
    color: #5f6b85;
    font-size: 13px;
    line-height: 1.55;
  }

  .assistant-timeline__list {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .assistant-timeline__loading {
    position: sticky;
    bottom: 0;
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: 42px;
    margin-top: 4px;
    padding: 12px 14px;
    border-radius: 18px;
    background:
      linear-gradient(180deg, rgba(255, 255, 255, 0.99), rgba(243, 247, 255, 0.97));
    border: 1px solid rgba(75, 120, 255, 0.14);
    box-shadow:
      0 12px 24px rgba(75, 120, 255, 0.10),
      inset 0 1px 0 rgba(255, 255, 255, 0.9);
    overflow: hidden;
  }

  .assistant-timeline__loading-ring {
    position: absolute;
    left: 14px;
    width: 22px;
    height: 22px;
    border-radius: 999px;
    background: radial-gradient(circle, rgba(75, 120, 255, 0.22), rgba(75, 120, 255, 0));
    animation: assistant-loading-breathe 1.8s ease-in-out infinite;
  }

  .assistant-timeline__activity {
    padding-top: 4px;
  }

  .assistant-timeline__loading-label {
    color: #58709c;
    font-size: 12px;
    font-weight: 600;
    line-height: 1.4;
  }

  .assistant-dot-pulse {
    position: relative;
    z-index: 1;
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .assistant-dot-pulse span {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: #4b78ff;
    animation: assistant-dot-pulse 1.4s infinite ease-in-out both;
  }

  .assistant-dot-pulse span:nth-child(1) {
    animation-delay: -0.32s;
  }

  .assistant-dot-pulse span:nth-child(2) {
    animation-delay: -0.16s;
  }

  @keyframes assistant-dot-pulse {
    0%, 80%, 100% {
      transform: scale(0.32);
      opacity: 0.35;
    }
    40% {
      transform: scale(1);
      opacity: 1;
      box-shadow: 0 0 12px rgba(75, 120, 255, 0.55);
    }
  }

  @keyframes assistant-loading-breathe {
    0%, 100% {
      transform: scale(0.88);
      opacity: 0.45;
    }
    50% {
      transform: scale(1.18);
      opacity: 1;
    }
  }
</style>
