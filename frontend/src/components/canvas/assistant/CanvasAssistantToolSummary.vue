<template>
  <section class="assistant-activity" data-testid="assistant-tool-summary">
    <div class="assistant-activity__header">
      <div>
        <div class="assistant-activity__eyebrow">Workflow activity</div>
        <h3 class="assistant-activity__title">{{ summaryText }}</h3>
      </div>
      <span class="assistant-activity__badge" :class="{ 'assistant-activity__badge--live': live || runningToolCount > 0 }">
        {{ live || runningToolCount > 0 ? `执行中 ${Math.max(1, runningToolCount)}` : '已同步' }}
      </span>
    </div>

    <div v-if="thinkingBuffer" class="assistant-activity__thinking">
      {{ thinkingBuffer }}
    </div>

    <div v-if="toolCalls.length" class="assistant-activity__list">
      <article
        v-for="toolCall in toolCalls"
        :key="toolCall.id"
        class="assistant-tool-card"
        :class="{ 'assistant-tool-card--running': toolCall.status !== 'completed' }"
      >
        <div class="assistant-tool-card__header">
          <span class="assistant-tool-card__dot" :class="`assistant-tool-card__dot--${toolCall.status || 'completed'}`"></span>
          <strong>{{ toolCall.toolName || 'unknown_tool' }}</strong>
          <span class="assistant-tool-card__status">{{ readStatusLabel(toolCall.status) }}</span>
        </div>
        <div v-if="readToolSummary(toolCall)" class="assistant-tool-card__summary">{{ readToolSummary(toolCall) }}</div>
      </article>
    </div>
  </section>
</template>

<script setup>
  import { computed } from 'vue'

  const props = defineProps({
    thinkingBuffer: { type: String, default: '' },
    toolCalls: { type: Array, default: () => [] },
    live: { type: Boolean, default: false }
  })

  const runningToolCount = computed(() =>
    props.toolCalls.filter((toolCall) => String(toolCall?.status || '').trim() !== 'completed').length
  )

  const summaryText = computed(() => {
    if (props.thinkingBuffer && props.toolCalls.length === 0) {
      return '思考中'
    }
    if (props.toolCalls.length > 0) {
      return `调用了 ${props.toolCalls.length} 个工具`
    }
    return '等待执行'
  })

  const readStatusLabel = (status) => {
    const normalized = String(status || 'completed').trim()
    if (normalized === 'requested' || normalized === 'running' || normalized === 'pending') return '执行中'
    if (normalized === 'failed') return '失败'
    return '已完成'
  }

  const readToolSummary = (toolCall) => {
    const result = toolCall?.result || {}
    const effect = toolCall?.effect || result?.effect || {}
    const displayMessage = result?.display?.message || result?.summary || effect?.summary
    if (displayMessage) return String(displayMessage)
    const args = toolCall?.args || {}
    if (args?.query) return `query: ${args.query}`
    if (args?.script_item_id) return `script_item_id: ${args.script_item_id}`
    const itemIds = args?.item_ids || args?.video_item_ids || args?.keyframe_item_ids || args?.character_image_item_ids
    if (Array.isArray(itemIds) && itemIds.length) return `节点数: ${itemIds.length}`
    return ''
  }
</script>

<style scoped>
  .assistant-activity {
    padding: 12px 14px;
    border-radius: 18px;
    border: 1px solid rgba(34, 57, 98, 0.08);
    background: rgba(255, 255, 255, 0.96);
    box-shadow: 0 10px 24px rgba(34, 57, 98, 0.06);
  }

  .assistant-activity__header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
  }

  .assistant-activity__eyebrow {
    color: #6a768f;
    font-size: 11px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
  }

  .assistant-activity__title {
    margin: 4px 0 0;
    color: #1f2a44;
    font-size: 15px;
    line-height: 1.35;
  }

  .assistant-activity__badge {
    padding: 6px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    background: #edf2f8;
    color: #52607a;
  }

  .assistant-activity__badge--live {
    background: #e7efff;
    color: #1855d6;
    animation: assistant-breathe 1.8s ease-in-out infinite;
  }

  .assistant-activity__thinking {
    margin-top: 10px;
    color: #52607a;
    font-size: 13px;
    line-height: 1.65;
    white-space: pre-wrap;
  }

  .assistant-activity__list {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-top: 12px;
  }

  .assistant-tool-card {
    padding: 10px 12px;
    border-radius: 14px;
    background: rgba(34, 57, 98, 0.04);
    border: 1px solid rgba(34, 57, 98, 0.06);
  }

  .assistant-tool-card--running {
    border-color: rgba(75, 120, 255, 0.18);
    box-shadow: inset 0 0 0 1px rgba(75, 120, 255, 0.04);
  }

  .assistant-tool-card__header {
    display: flex;
    align-items: center;
    gap: 8px;
    color: #1f2a44;
    font-size: 13px;
  }

  .assistant-tool-card__dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #0f6a36;
  }

  .assistant-tool-card__dot--requested,
  .assistant-tool-card__dot--running,
  .assistant-tool-card__dot--pending {
    background: #4b78ff;
    animation: assistant-breathe 1.4s ease-in-out infinite;
  }

  .assistant-tool-card__dot--failed {
    background: #b42318;
  }

  .assistant-tool-card__status {
    margin-left: auto;
    color: #6a768f;
    font-size: 12px;
  }

  .assistant-tool-card__summary {
    margin: 8px 0 0;
    color: #5b6884;
    font-size: 12px;
    line-height: 1.55;
    white-space: pre-wrap;
    word-break: break-word;
  }

  @keyframes assistant-breathe {
    0%,
    100% {
      box-shadow: 0 0 0 0 rgba(75, 120, 255, 0.22);
    }
    50% {
      box-shadow: 0 0 0 8px rgba(75, 120, 255, 0);
    }
  }
</style>
