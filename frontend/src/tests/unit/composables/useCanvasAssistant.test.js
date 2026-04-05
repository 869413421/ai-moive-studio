/**
 * @vitest-environment jsdom
 */

import { createApp, defineComponent, nextTick, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/services/canvasAssistant', () => ({
  canvasAssistantService: {
    chat: vi.fn(async (_payload, handlers) => {
      handlers?.onEvent?.({ kind: 'session', sessionId: 'session-1' })
      handlers?.onEvent?.({
        kind: 'tool',
        toolCall: {
          id: 'tool-1',
          toolName: 'canvas.update_item',
          status: 'completed',
          result: {
            effect: { mutated: true, updated_item_ids: ['item-1'], needs_refresh: true, refresh_scopes: ['document'] }
          },
          order: 1
        }
      })
      handlers?.onEvent?.({
        kind: 'interrupt',
        interrupt: {
          interruptId: 'interrupt-1',
          sessionId: 'session-1',
          kind: 'confirm_delete',
          title: '确认删除',
          message: '这是高风险动作，需要确认。',
          actions: ['approve', 'reject'],
          selectedModelId: ''
        }
      })
      return { events: [] }
    }),
    resume: vi.fn(async (_payload, handlers) => {
      handlers?.onEvent?.({
        kind: 'tool',
        toolCall: {
          id: 'tool-2',
          toolName: 'canvas.delete_items',
          status: 'completed',
          result: {
            effect: { mutated: true, deleted_item_ids: ['item-1'], needs_refresh: true, refresh_scopes: ['document'] }
          },
          order: 2
        }
      })
      handlers?.onEvent?.({
        kind: 'message',
        message: { id: 'assistant-1', role: 'assistant', delta: '已删除目标节点。', order: 5 }
      })
      handlers?.onEvent?.({
        kind: 'message_completed',
        message: { id: 'assistant-1', role: 'assistant', content: '已删除目标节点。', order: 5 }
      })
      handlers?.onEvent?.({ kind: 'done', data: { session_id: 'session-1' } })
      return { events: [] }
    })
  }
}))

vi.mock('@/services/apiKeys', () => ({
  apiKeysService: {
    getAPIKeys: vi.fn().mockResolvedValue({
      api_keys: [{ id: 'key-1', name: '主 Key', provider: 'openai' }]
    }),
    getAPIKeyModels: vi.fn().mockResolvedValue(['gpt-4o-mini'])
  }
}))

import { useCanvasAssistant } from '@/composables/useCanvasAssistant'
import { canvasAssistantService } from '@/services/canvasAssistant'

const mountComposable = () => {
  let assistant = null
  const onMutationApplied = vi.fn()
  const app = createApp(
    defineComponent({
      setup() {
        assistant = useCanvasAssistant({
          documentId: ref('doc-1'),
          onMutationApplied
        })
        return () => null
      }
    })
  )
  app.mount(document.createElement('div'))
  return { app, onMutationApplied, get assistant() { return assistant } }
}

describe('useCanvasAssistant', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('drives the ReAct event stream and resume flow without selected nodes', async () => {
    const { app, assistant, onMutationApplied } = mountComposable()
    await nextTick()
    await Promise.resolve()
    await Promise.resolve()

    await assistant.sendMessage('删除开场节点')
    await nextTick()

    expect(canvasAssistantService.chat).toHaveBeenCalledWith(
      expect.objectContaining({
        documentId: 'doc-1',
        message: '删除开场节点'
      }),
      expect.any(Object)
    )
    expect(Array.isArray(assistant.eventLog.value)).toBe(true)
    expect(assistant.eventLog.value.map((event) => event.kind)).toEqual([
      'message',
      'session',
      'tool',
      'interrupt'
    ])
    expect(assistant.pendingInterrupt.value).toMatchObject({
      interruptId: 'interrupt-1',
      kind: 'confirm_delete'
    })
    expect(assistant.canSend.value).toBe(false)

    await assistant.resumeInterrupt({
      decision: 'approve',
      selectedModelId: 'model-a'
    })
    await nextTick()

    expect(canvasAssistantService.resume).toHaveBeenCalledWith(
      expect.objectContaining({
        documentId: 'doc-1',
        sessionId: 'session-1',
        interruptId: 'interrupt-1',
        decision: 'approve',
        selectedModelId: 'model-a'
      }),
      expect.any(Object)
    )
    expect(assistant.messages.value.at(-1)).toMatchObject({
      role: 'assistant',
      content: '已删除目标节点。'
    })
    expect(assistant.eventLog.value.some((event) => event.kind === 'done')).toBe(true)
    expect(assistant.eventLog.value.at(-1)).toMatchObject({
      kind: 'interrupt_resolved'
    })
    expect(onMutationApplied).toHaveBeenLastCalledWith(
      expect.objectContaining({
        documentId: 'doc-1',
        sessionId: 'session-1',
        scopes: ['document']
      })
    )

    app.unmount()
  })

  it('refreshes canvas after auto-executed mutations from chat turns', async () => {
    canvasAssistantService.chat.mockImplementationOnce(async (_payload, handlers) => {
      handlers?.onEvent?.({ kind: 'session', sessionId: 'session-2' })
      handlers?.onEvent?.({
        kind: 'tool',
        toolCall: {
          id: 'tool-auto',
          toolName: 'canvas.update_item',
          status: 'completed',
          result: {
            effect: { mutated: true, updated_item_ids: ['item-2'], needs_refresh: true, refresh_scopes: ['document'] }
          },
          order: 1
        }
      })
      handlers?.onEvent?.({
        kind: 'message',
        message: { id: 'assistant-2', role: 'assistant', delta: '已更新开场标题。', order: 2 }
      })
      handlers?.onEvent?.({ kind: 'done', data: { session_id: 'session-2' } })
      return { events: [] }
    })

    const { app, assistant, onMutationApplied } = mountComposable()
    await nextTick()
    await Promise.resolve()
    await Promise.resolve()

    await assistant.sendMessage('把开场标题改成雨夜开场')
    await nextTick()

    expect(onMutationApplied).toHaveBeenCalledWith(
      expect.objectContaining({
        documentId: 'doc-1',
        sessionId: 'session-2'
      })
    )

    app.unmount()
  })
})
