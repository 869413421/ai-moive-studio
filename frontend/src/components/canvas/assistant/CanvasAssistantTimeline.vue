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
        <template v-for="item in items" :key="item.id">
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
          <CanvasAssistantToolSummary
            v-else-if="item.type === 'activity'"
            :activity="item.activity"
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

      <div v-if="busy" class="assistant-timeline__loading">
        <div class="assistant-dot-pulse">
          <span></span><span></span><span></span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
  import { nextTick, ref, watch } from 'vue'
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
    display: flex;
    align-items: center;
    min-height: 22px;
    padding: 4px 2px 8px;
  }

  .assistant-dot-pulse {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .assistant-dot-pulse span {
    width: 6px;
    height: 6px;
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
      transform: scale(0);
      opacity: 0.35;
    }
    40% {
      transform: scale(1);
      opacity: 1;
      box-shadow: 0 0 8px rgba(75, 120, 255, 0.45);
    }
  }
</style>
