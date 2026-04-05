import { computed, ref, watch } from 'vue'
import { canvasAssistantService } from '@/services/canvasAssistant'
import { apiKeysService } from '@/services/apiKeys'
import { reduceCanvasAssistantEventLog } from '@/composables/useCanvasAssistantTimeline'

const buildMessageId = (prefix, turnId) => `${prefix}-${turnId}-${Date.now()}`

export function useCanvasAssistant({
  documentId = '',
  service = canvasAssistantService,
  onMutationApplied = null
} = {}) {
  const sessionId = ref('')
  const runtimeError = ref('')
  const eventLog = ref([])
  const apiKeysLoading = ref(false)
  const chatModelsLoading = ref(false)
  const apiKeyOptions = ref([])
  const chatModelOptions = ref([])
  const selectedApiKeyId = ref('')
  const selectedChatModelId = ref('')
  const pendingInterruptSelectedModelId = ref('')
  const currentTurnId = ref(0)
  const abortController = ref(null)
  const lastRefreshSignature = ref('')

  const resolvedDocumentId = computed(() => String(documentId?.value ?? documentId ?? '').trim())
  const reducedState = computed(() =>
    reduceCanvasAssistantEventLog({
      eventLog: eventLog.value,
      selectedModelId: pendingInterruptSelectedModelId.value
    })
  )

  const messages = computed(() => reducedState.value.messages)
  const pendingInterrupt = computed(() => reducedState.value.pendingInterrupt)
  const error = computed(() => String(runtimeError.value || reducedState.value.fatalError || '').trim())
  const status = computed(() => reducedState.value.status)
  const isStreaming = computed(() => reducedState.value.isStreaming)
  const activeTool = computed(() => reducedState.value.activeTool)
  const refreshRequest = computed(() => reducedState.value.refreshRequest)

  const canSend = computed(
    () =>
      !isStreaming.value &&
      !pendingInterrupt.value &&
      Boolean(selectedApiKeyId.value) &&
      Boolean(selectedChatModelId.value) &&
      Boolean(resolvedDocumentId.value)
  )

  const normalizeApiKeyOptions = (response) => {
    const apiKeys = Array.isArray(response?.api_keys) ? response.api_keys : []
    return apiKeys
      .map((item) => ({
        id: String(item?.id || '').trim(),
        label: String(item?.name || item?.id || '').trim(),
        provider: String(item?.provider || '').trim()
      }))
      .filter((item) => item.id)
  }

  const normalizeModelOptions = (response) => {
    const rawModels = Array.isArray(response) ? response : Array.isArray(response?.models) ? response.models : []
    return rawModels.map((item) => String(item || '').trim()).filter(Boolean)
  }

  const loadChatModels = async (apiKeyId) => {
    const normalizedApiKeyId = String(apiKeyId || '').trim()
    chatModelsLoading.value = true
    try {
      if (!normalizedApiKeyId) {
        chatModelOptions.value = []
        selectedChatModelId.value = ''
        return []
      }
      const models = normalizeModelOptions(await apiKeysService.getAPIKeyModels(normalizedApiKeyId, 'text'))
      chatModelOptions.value = models
      if (!models.includes(selectedChatModelId.value)) {
        selectedChatModelId.value = models[0] || ''
      }
      return models
    } finally {
      chatModelsLoading.value = false
    }
  }

  const loadApiKeys = async () => {
    apiKeysLoading.value = true
    try {
      const options = normalizeApiKeyOptions(
        await apiKeysService.getAPIKeys({ page: 1, size: 100, key_status: 'active' })
      )
      apiKeyOptions.value = options
      if (!options.some((item) => item.id === selectedApiKeyId.value)) {
        selectedApiKeyId.value = options[0]?.id || ''
      }
      await loadChatModels(selectedApiKeyId.value)
      return options
    } finally {
      apiKeysLoading.value = false
    }
  }

  const appendEvent = (nextEvent) => {
    if (!nextEvent || typeof nextEvent !== 'object') return
    eventLog.value = [...eventLog.value, nextEvent]
  }

  const applyEvent = (event) => {
    if (!event || typeof event !== 'object') return
    appendEvent(event)
    if (event.kind === 'session') {
      sessionId.value = String(event.sessionId || '').trim()
      return
    }
    if (event.kind === 'interrupt') {
      pendingInterruptSelectedModelId.value = String(event.interrupt?.selectedModelId || '').trim()
      return
    }
    if (event.kind === 'interrupt_resolved') {
      pendingInterruptSelectedModelId.value = ''
      return
    }
    if (event.kind === 'error') {
      runtimeError.value = String(event.message || 'assistant request failed').trim()
    }
  }

  watch(
    refreshRequest,
    async (nextValue, previousValue) => {
      if (!nextValue || nextValue === previousValue) return
      const signature = JSON.stringify(nextValue)
      if (signature === lastRefreshSignature.value) return
      lastRefreshSignature.value = signature
      try {
        await Promise.resolve(
          onMutationApplied?.({
            documentId: resolvedDocumentId.value,
            sessionId: sessionId.value,
            scopes: nextValue.scopes,
            effect: nextValue.effect
          })
        )
      } catch (refreshError) {
        console.error('Refresh canvas after assistant mutation failed', refreshError)
      }
    },
    { deep: true }
  )

  const runTurn = async (turnRunner) => {
    abortController.value?.abort?.()
    abortController.value = new AbortController()
    runtimeError.value = ''
    try {
      return await turnRunner(abortController.value.signal)
    } catch (turnError) {
      runtimeError.value = turnError?.message || 'assistant request failed'
      throw turnError
    } finally {
      abortController.value = null
    }
  }

  const ensureChatContextReady = async () => {
    if (!selectedApiKeyId.value) {
      await loadApiKeys()
    }
    if (selectedApiKeyId.value && !selectedChatModelId.value) {
      await loadChatModels(selectedApiKeyId.value)
    }
    if (!selectedApiKeyId.value || !selectedChatModelId.value) {
      throw new Error('缺少对话 Key 或对话模型，未调用大模型。')
    }
  }

  const sendMessage = async (message) => {
    const trimmedMessage = String(message || '').trim()
    if (!trimmedMessage || isStreaming.value || pendingInterrupt.value || !resolvedDocumentId.value) {
      return false
    }

    try {
      await ensureChatContextReady()
    } catch (contextError) {
      runtimeError.value = contextError?.message || '缺少对话 Key 或对话模型'
      return false
    }

    currentTurnId.value += 1
    appendEvent({
      kind: 'message',
      message: {
        id: buildMessageId('user', currentTurnId.value),
        role: 'user',
        content: trimmedMessage,
        order: messages.value.length + 1
      }
    })

    await runTurn((signal) =>
      service.chat(
        {
          documentId: resolvedDocumentId.value,
          sessionId: sessionId.value,
          message: trimmedMessage,
          apiKeyId: selectedApiKeyId.value,
          chatModelId: selectedChatModelId.value
        },
        { onEvent: applyEvent, signal }
      )
    )

    return true
  }

  const updatePendingInterruptModelId = (selectedModelId) => {
    if (!pendingInterrupt.value) return
    pendingInterruptSelectedModelId.value = String(selectedModelId || '').trim()
  }

  const resumeInterrupt = async ({ decision = 'approve', selectedModelId = '' } = {}) => {
    if (!pendingInterrupt.value || isStreaming.value) {
      return false
    }
    const interruptSnapshot = pendingInterrupt.value
    updatePendingInterruptModelId(selectedModelId)
    await runTurn((signal) =>
      service.resume(
        {
          documentId: resolvedDocumentId.value,
          sessionId: interruptSnapshot.sessionId || sessionId.value,
          interruptId: interruptSnapshot.interruptId,
          decision,
          selectedModelId: pendingInterruptSelectedModelId.value
        },
        { onEvent: applyEvent, signal }
      )
    )
    appendEvent({
      kind: 'interrupt_resolved',
      interrupt: { interruptId: interruptSnapshot.interruptId, decision }
    })
    pendingInterruptSelectedModelId.value = ''
    return true
  }

  const reset = () => {
    abortController.value?.abort?.()
    sessionId.value = ''
    runtimeError.value = ''
    eventLog.value = []
    pendingInterruptSelectedModelId.value = ''
    currentTurnId.value = 0
    lastRefreshSignature.value = ''
  }

  loadApiKeys().catch(() => {
    runtimeError.value = '加载 assistant 对话模型失败'
  })

  return {
    eventLog,
    sessionId,
    status,
    error,
    messages,
    pendingInterrupt,
    apiKeysLoading,
    chatModelsLoading,
    apiKeyOptions,
    chatModelOptions,
    selectedApiKeyId,
    selectedChatModelId,
    isStreaming,
    canSend,
    activeTool,
    refreshRequest,
    sendMessage,
    updateSelectedApiKeyId: async (apiKeyId) => {
      selectedApiKeyId.value = String(apiKeyId || '').trim()
      await loadChatModels(selectedApiKeyId.value)
    },
    updateSelectedChatModelId: (chatModelId) => {
      selectedChatModelId.value = String(chatModelId || '').trim()
    },
    resumeInterrupt,
    updatePendingInterruptModelId,
    reset
  }
}

export default useCanvasAssistant
