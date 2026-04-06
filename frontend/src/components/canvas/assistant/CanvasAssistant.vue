<template>
  <aside
    class="canvas-assistant"
    style="user-select: text; -webkit-user-select: text"
  >
    <CanvasAssistantHeader
      :title="title"
      :status="status"
      :session-id="sessionId"
      :can-reset="canReset"
      :streaming="isStreaming"
      @reset="handleReset"
    />

    <CanvasAssistantTimeline
      class="canvas-assistant__timeline"
      :items="timelineItems"
      :busy="isStreaming"
      @approve="handleApprove"
      @reject="handleReject"
      @update:selected-model-id="handleUpdateSelectedModelId"
    />

    <div v-if="showBottomStreamingGlow" class="canvas-assistant__stream-indicator" data-testid="assistant-stream-indicator">
      <span class="canvas-assistant__stream-indicator-ring"></span>
      <span class="canvas-assistant__stream-indicator-dot"></span>
      <span class="canvas-assistant__stream-indicator-text">
        {{ activeTool ? `正在执行 ${activeTool}` : 'Assistant 正在处理当前工作流' }}
      </span>
    </div>

    <CanvasAssistantComposer
      class="canvas-assistant__composer"
      :disabled="!canSend"
      :loading="isStreaming"
      :placeholder="composerPlaceholder"
      :api-key-options="apiKeyOptions"
      :chat-model-options="chatModelOptions"
      :selected-api-key-id="selectedApiKeyId"
      :selected-chat-model-id="selectedChatModelId"
      :api-keys-loading="apiKeysLoading"
      :chat-models-loading="chatModelsLoading"
      @update:selected-api-key-id="handleUpdateSelectedApiKeyId"
      @update:selected-chat-model-id="handleUpdateSelectedChatModelId"
      @submit="handleSend"
    />
  </aside>
</template>

<script setup>
  import { computed } from 'vue'
  import useCanvasAssistant from '@/composables/useCanvasAssistant'
  import { useCanvasAssistantTimeline } from '@/composables/useCanvasAssistantTimeline'
  import CanvasAssistantComposer from './CanvasAssistantComposer.vue'
  import CanvasAssistantHeader from './CanvasAssistantHeader.vue'
  import CanvasAssistantTimeline from './CanvasAssistantTimeline.vue'

  const props = defineProps({
    // documentId: 当前画布 id，用来绑定 assistant 会话和上下文。
    documentId: { type: String, default: '' },
    refreshCanvas: { type: Function, default: null },
    // title: 右侧助手栏标题，默认保持通用文案。
    title: { type: String, default: 'AI 助手' }
  })

  // assistant composable 负责真实状态机；组件本身只拼装头部、时间线和输入区。
  const assistant = useCanvasAssistant({
    documentId: computed(() => props.documentId),
    onMutationApplied: (...args) => props.refreshCanvas?.(...args)
  })
  const sessionId = assistant.sessionId
  const status = assistant.status
  const error = assistant.error
  const messages = assistant.messages
  const eventLog = assistant.eventLog ?? computed(() => [])
  const pendingInterrupt = assistant.pendingInterrupt ?? computed(() => null)
  const apiKeyOptions = assistant.apiKeyOptions
  const chatModelOptions = assistant.chatModelOptions
  const selectedApiKeyId = assistant.selectedApiKeyId
  const selectedChatModelId = assistant.selectedChatModelId
  const apiKeysLoading = assistant.apiKeysLoading
  const chatModelsLoading = assistant.chatModelsLoading
  const isStreaming = assistant.isStreaming
  const canSend = assistant.canSend
  const sendMessage = assistant.sendMessage
  const updateSelectedApiKeyId = assistant.updateSelectedApiKeyId
  const updateSelectedChatModelId = assistant.updateSelectedChatModelId
  const resumeInterrupt = assistant.resumeInterrupt ?? (() => false)
  const updatePendingInterruptModelId = assistant.updatePendingInterruptModelId ?? (() => {})
  const reset = assistant.reset

  const { timelineItems } = useCanvasAssistantTimeline(assistant)

  const canReset = computed(
    () =>
      eventLog.value.length > 0 ||
      messages.value.length > 0 ||
      Boolean(pendingInterrupt.value) ||
      Boolean(error.value)
  )
  const showBottomStreamingGlow = computed(
    () => Boolean(isStreaming.value || activeTool.value || status.value === 'streaming')
  )
  const composerPlaceholder = computed(() => '描述你想让画布帮你完成的事情')

  const handleSend = (message) => sendMessage(message)
  const handleUpdateSelectedApiKeyId = (apiKeyId) => updateSelectedApiKeyId(apiKeyId)
  const handleUpdateSelectedChatModelId = (chatModelId) => updateSelectedChatModelId(chatModelId)
  const handleApprove = (selectedModelId) =>
    resumeInterrupt({ decision: 'approve', selectedModelId })
  const handleReject = () => resumeInterrupt({ decision: 'reject' })
  const handleUpdateSelectedModelId = (selectedModelId) =>
    updatePendingInterruptModelId(selectedModelId)
  const handleReset = () => reset()

  defineExpose({
    ...assistant
  })
</script>

<style scoped>
  .canvas-assistant {
    height: 100%;
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 18px;
    border-left: 1px solid rgba(34, 57, 98, 0.08);
    background:
      linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(246, 249, 255, 0.94)),
      radial-gradient(circle at top, rgba(75, 120, 255, 0.08), transparent 34%);
    backdrop-filter: blur(18px);
    box-shadow: inset 1px 0 0 rgba(255, 255, 255, 0.6);
    user-select: text;
    -webkit-user-select: text;
  }

  .canvas-assistant__timeline {
    flex: 1;
    min-height: 0;
  }

  .canvas-assistant__composer {
    flex: 0 0 auto;
  }

  .canvas-assistant__stream-indicator {
    position: relative;
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: 18px;
    padding: 4px 2px 2px;
    color: #4b78ff;
  }

  .canvas-assistant__stream-indicator-ring {
    position: absolute;
    left: -2px;
    width: 22px;
    height: 22px;
    border-radius: 999px;
    background: radial-gradient(circle, rgba(75, 120, 255, 0.24), rgba(75, 120, 255, 0));
    animation: canvas-assistant-stream-breathe 1.9s ease-in-out infinite;
  }

  .canvas-assistant__stream-indicator-dot {
    position: relative;
    z-index: 1;
    width: 8px;
    height: 8px;
    border-radius: 999px;
    background: #4b78ff;
    box-shadow: 0 0 10px rgba(75, 120, 255, 0.55);
    animation: canvas-assistant-stream-dot 1.2s ease-in-out infinite;
  }

  .canvas-assistant__stream-indicator-text {
    position: relative;
    z-index: 1;
    font-size: 12px;
    font-weight: 600;
    line-height: 1.4;
    color: #5a74a8;
  }

  @keyframes canvas-assistant-stream-breathe {
    0%, 100% {
      transform: scale(0.82);
      opacity: 0.42;
    }
    50% {
      transform: scale(1.16);
      opacity: 1;
    }
  }

  @keyframes canvas-assistant-stream-dot {
    0%, 100% {
      transform: scale(0.9);
      opacity: 0.65;
    }
    50% {
      transform: scale(1.08);
      opacity: 1;
    }
  }
</style>
