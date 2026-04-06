import { computed, unref } from 'vue'

const readOrder = (value, fallback = 0) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

const buildMessageKey = (message = {}, fallbackOrder = 0) =>
  String(message.id || `message-${fallbackOrder}`).trim()

const normalizeMessageTimelineItem = (message = {}, fallbackOrder = 0) => ({
  id: buildMessageKey(message, fallbackOrder),
  type: `${String(message.role || 'assistant').trim() === 'user' ? 'user' : 'assistant'}_message`,
  order: readOrder(message.order, fallbackOrder),
  message: {
    id: buildMessageKey(message, fallbackOrder),
    role: String(message.role || 'assistant').trim() === 'user' ? 'user' : 'assistant',
    content: String(message.content || '').trim()
  }
})

const normalizeActivityTimelineItem = (activity = {}, fallbackOrder = 0) => ({
  id: String(activity.id || `activity-${fallbackOrder}`).trim(),
  type: 'activity',
  order: readOrder(activity.order, fallbackOrder),
  activity: {
    id: String(activity.id || `activity-${fallbackOrder}`).trim(),
    activityType: 'tool',
    title: String(activity.title || '').trim(),
    toolName: String(activity.toolName || '').trim(),
    status: String(activity.status || 'completed').trim() || 'completed',
    args: activity.args ?? null,
    result: activity.result ?? null
  }
})

const normalizeToolSummaryItem = (
  { thinkingBuffer = '', toolCalls = [], order = 0 } = {},
  fallbackOrder = 0
) => ({
  id: 'tool-summary',
  type: 'tool_summary',
  order: readOrder(order, fallbackOrder),
  thinkingBuffer: String(thinkingBuffer || '').trim(),
  toolCalls: Array.isArray(toolCalls) ? toolCalls : []
})

const normalizeInterruptItem = (interrupt = {}, fallbackOrder = 0) => ({
  id: String(interrupt.interruptId || `interrupt-${fallbackOrder}`).trim(),
  type: 'interrupt_card',
  order: readOrder(interrupt.order, fallbackOrder),
  interrupt: {
    interruptId: String(interrupt.interruptId || '').trim(),
    sessionId: String(interrupt.sessionId || '').trim(),
    kind: String(interrupt.kind || '').trim(),
    title: String(interrupt.title || '').trim(),
    message: String(interrupt.message || '').trim(),
    actions: Array.isArray(interrupt.actions) ? interrupt.actions : [],
    selectedModelId: String(interrupt.selectedModelId || '').trim(),
    modelOptions: Array.isArray(interrupt.modelOptions) ? interrupt.modelOptions : []
  }
})

const normalizeErrorItem = (message = '', order = Number.MAX_SAFE_INTEGER) => ({
  id: 'assistant-error',
  type: 'error_notice',
  order,
  message: String(message || '').trim()
})

export const reduceCanvasAssistantEventLog = ({ eventLog = [], selectedModelId = '' } = {}) => {
  const messages = []
  const activities = []
  let thinkingBuffer = ''
  let thinkingOrder = 0
  let pendingInterrupt = null
  let refreshRequest = null
  let activeTool = null
  let fatalError = ''
  let status = 'idle'
  let isStreaming = false

  const upsertMessage = (message = {}) => {
    const normalized = {
      id: buildMessageKey(message, messages.length + 1),
      role: String(message.role || 'assistant').trim() === 'user' ? 'user' : 'assistant',
      content: String(message.content || message.delta || ''),
      order: readOrder(message.order, messages.length + 1)
    }
    const index = messages.findIndex((item) => item.id === normalized.id)
    if (index >= 0) {
      const previous = messages[index]
      messages[index] = {
        ...previous,
        ...normalized,
        content: typeof message.delta === 'string' ? `${String(previous.content || '')}${message.delta}` : normalized.content
      }
      return
    }
    if (normalized.role === 'user') {
      thinkingBuffer = ''
      thinkingOrder = normalized.order
      activities.splice(0, activities.length)
      activeTool = null
    }
    messages.push(normalized)
  }

  const upsertActivity = (payload = {}) => {
    const normalized = {
      id: String(payload.id || `tool-${activities.length + 1}`).trim(),
      title: String(payload.title || '').trim(),
      toolName: String(payload.toolName || '').trim(),
      status: String(payload.status || 'completed').trim() || 'completed',
      args: payload.args ?? null,
      result: payload.result ?? null,
      order: readOrder(payload.order, activities.length + 1)
    }
    const index = activities.findIndex((item) => item.id === normalized.id)
    if (index >= 0) {
      activities[index] = { ...activities[index], ...normalized }
      return
    }
    activities.push(normalized)
  }

  for (const event of Array.isArray(eventLog) ? eventLog : []) {
    if (!event || typeof event !== 'object') continue
    switch (event.kind) {
      case 'session':
        status = 'streaming'
        isStreaming = true
        break
      case 'message':
      case 'message_completed':
        upsertMessage(event.message || {})
        status = 'streaming'
        if (event.kind === 'message_completed') {
          isStreaming = false
        }
        break
      case 'thinking':
        {
          const chunk = String(event.thinking?.content || '').trim()
          if (chunk && !thinkingBuffer.endsWith(chunk)) {
            thinkingBuffer += chunk
          }
        }
        if (!thinkingOrder) {
          thinkingOrder = readOrder(event.thinking?.order, event.order)
        }
        status = 'streaming'
        isStreaming = true
        break
      case 'tool':
        upsertActivity(event.toolCall || {})
        activeTool = String(event.toolCall?.toolName || '').trim() || activeTool
        status = 'streaming'
        if (event.toolCall?.status === 'completed') {
          activeTool = null
          const effect = event.toolCall?.effect || event.toolCall?.result?.effect || {}
          if (effect?.needs_refresh) {
            refreshRequest = {
              scopes: Array.isArray(effect.refresh_scopes) ? effect.refresh_scopes : [],
              effect
            }
          }
        }
        break
      case 'interrupt':
        pendingInterrupt = {
          interruptId: String(event.interrupt?.interruptId || '').trim(),
          sessionId: String(event.interrupt?.sessionId || '').trim(),
          kind: String(event.interrupt?.kind || '').trim(),
          title: String(event.interrupt?.title || '').trim(),
          message: String(event.interrupt?.message || '').trim(),
          actions: Array.isArray(event.interrupt?.actions) ? event.interrupt.actions : [],
          selectedModelId: String(selectedModelId || event.interrupt?.selectedModelId || '').trim(),
          modelOptions: Array.isArray(event.interrupt?.modelOptions) ? event.interrupt.modelOptions : [],
          order: readOrder(event.interrupt?.order, event.order)
        }
        status = 'awaiting_interrupt'
        isStreaming = false
        break
      case 'interrupt_resolved':
        pendingInterrupt = null
        status = 'streaming'
        isStreaming = true
        break
      case 'error':
        fatalError = String(event.message || '').trim()
        status = 'error'
        isStreaming = false
        activeTool = null
        break
      case 'done':
        isStreaming = false
        if (!pendingInterrupt && !fatalError) {
          status = 'idle'
        }
        activeTool = null
        break
      default:
        break
    }
  }

  return {
    messages: [...messages].sort((left, right) => readOrder(left.order) - readOrder(right.order)),
    timelineActivities: [...activities].sort((left, right) => readOrder(left.order) - readOrder(right.order)),
    thinkingBuffer,
    thinkingOrder,
    pendingInterrupt,
    refreshRequest,
    activeTool,
    fatalError,
    error: fatalError,
    status,
    isStreaming
  }
}

export const buildCanvasAssistantTimelineItems = ({ eventLog = [] } = {}) => {
  const reduced = reduceCanvasAssistantEventLog({ eventLog })
  const items = [
    ...(Array.isArray(reduced.messages) ? reduced.messages : []).map((message, index) =>
      normalizeMessageTimelineItem(message, index + 1)
    )
  ]
  if (String(reduced.thinkingBuffer || '').trim() || (Array.isArray(reduced.timelineActivities) && reduced.timelineActivities.length > 0)) {
    const toolSummaryItem = normalizeToolSummaryItem(
      {
        thinkingBuffer: reduced.thinkingBuffer,
        toolCalls: reduced.timelineActivities,
        order: reduced.thinkingOrder || reduced.timelineActivities[0]?.order || items.length + 1
      },
      items.length + 1
    )
    const insertIndex = items.findIndex(
      (item) => item.type === 'assistant_message' && readOrder(item.order, 0) >= readOrder(toolSummaryItem.order, 0)
    )
    if (insertIndex >= 0) {
      items.splice(insertIndex, 0, toolSummaryItem)
    } else {
      items.push(toolSummaryItem)
    }
  }
  if (reduced.pendingInterrupt) {
    items.push(normalizeInterruptItem({ ...reduced.pendingInterrupt, order: items.length + 1 }, items.length + 1))
  }
  if (String(reduced.fatalError || '').trim()) {
    items.push(normalizeErrorItem(reduced.fatalError, items.length + 1))
  }
  return items
}

export function useCanvasAssistantTimeline(source = {}) {
  const timelineItems = computed(() =>
    buildCanvasAssistantTimelineItems({
      eventLog: unref(source.eventLog) || []
    })
  )

  return { timelineItems }
}

export default useCanvasAssistantTimeline
