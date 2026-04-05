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
</style>
