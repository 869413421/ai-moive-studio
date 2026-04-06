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
            :live="busy && item.type === 'assistant_message' && item.message?.id === lastAssistantMessageId"
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
  const conversationItems = computed(() => {
    const list = (Array.isArray(props.items) ? props.items : []).filter((item) => item?.type !== 'tool_summary')
    if (!props.busy) {
      return list
    }
    const hasAssistantMessage = list.some((item) => item?.type === 'assistant_message')
    if (hasAssistantMessage) {
      return list
    }
    return [
      ...list,
      {
        id: 'assistant-live-placeholder',
        type: 'assistant_message',
        order: (list[list.length - 1]?.order || 0) + 1,
        message: {
          id: 'assistant-live-placeholder',
          role: 'assistant',
          content: ''
        }
      }
    ]
  })
  const lastAssistantMessageId = computed(() => {
    const list = conversationItems.value.filter((item) => item?.type === 'assistant_message')
    return list.length ? String(list[list.length - 1]?.message?.id || '') : ''
  })
  const activitySummary = computed(() => {
    const summaries = (Array.isArray(props.items) ? props.items : []).filter((item) => item?.type === 'tool_summary')
    return summaries.length ? summaries[summaries.length - 1] : null
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
  .assistant-timeline__activity {
    padding-top: 4px;
  }
</style>
