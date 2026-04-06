/**
 * @vitest-environment jsdom
 */

import { computed, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import CanvasAssistant from '@/components/canvas/assistant/CanvasAssistant.vue'
import { useCanvasAssistant } from '@/composables/useCanvasAssistant'
import { useCanvasAssistantTimeline } from '@/composables/useCanvasAssistantTimeline'

vi.mock('@/composables/useCanvasAssistant', () => {
  const useCanvasAssistant = vi.fn()
  return {
    useCanvasAssistant,
    default: useCanvasAssistant
  }
})

vi.mock('@/composables/useCanvasAssistantTimeline', () => {
  const useCanvasAssistantTimeline = vi.fn()
  return {
    useCanvasAssistantTimeline,
    default: useCanvasAssistantTimeline
  }
})

describe('CanvasAssistant', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the assistant rail and forwards composer and confirmation actions', async () => {
    const sendMessage = vi.fn()
    const resumeConfirmation = vi.fn()
    const updatePendingConfirmationModelId = vi.fn()
    const reset = vi.fn()

    useCanvasAssistant.mockReturnValue({
      sessionId: ref('session-1'),
      status: ref('awaiting_interrupt'),
      error: ref(''),
      eventLog: ref([
        { kind: 'message', message: { id: 'm-1', role: 'user', content: '请看一下', order: 1 } },
        {
          kind: 'tool',
          toolCall: {
            id: 't-1',
            toolName: 'canvas.find_items',
            status: 'completed',
            args: { query: '开场' },
            result: { items: [{ id: 'item-1' }] },
            order: 3
          }
        },
        {
          kind: 'interrupt',
          interrupt: {
            interruptId: 'interrupt-1',
            sessionId: 'session-1',
            kind: 'confirm_execute',
            title: '确认执行',
            message: '请选择模型后继续',
            selectedModelId: '',
            modelOptions: [
              { modelId: 'model-a', label: '模型 A', resolution: '1024x1024' }
            ],
            actions: ['approve', 'reject']
          }
        }
      ]),
      messages: ref([
        { id: 'm-1', role: 'user', content: '请看一下', order: 1 }
      ]),
      pendingInterrupt: ref({
        interruptId: 'interrupt-1',
        sessionId: 'session-1',
        kind: 'confirm_execute',
        title: '确认执行',
        message: '请选择模型后继续',
        selectedModelId: '',
        modelOptions: [
          { modelId: 'model-a', label: '模型 A', resolution: '1024x1024' }
        ],
        actions: ['approve', 'reject']
      }),
      apiKeyOptions: ref([
        { id: 'key-1', label: '主 Key', provider: 'openai' }
      ]),
      chatModelOptions: ref(['gpt-4o-mini', 'gpt-4o']),
      selectedApiKeyId: ref('key-1'),
      selectedChatModelId: ref('gpt-4o-mini'),
      apiKeysLoading: ref(false),
      chatModelsLoading: ref(false),
      isStreaming: ref(false),
      canSend: ref(true),
      sendMessage,
      updateSelectedApiKeyId: vi.fn(),
      updateSelectedChatModelId: vi.fn(),
      resumeInterrupt: resumeConfirmation,
      updatePendingInterruptModelId: updatePendingConfirmationModelId,
      reset
    })

    useCanvasAssistantTimeline.mockReturnValue({
      timelineItems: computed(() => [
        {
          id: 'm-1',
          type: 'user_message',
          message: { role: 'user', content: '请看一下', order: 1 }
        },
        {
          id: 'tool-summary',
          type: 'tool_summary',
          thinkingBuffer: '先定位开场节点，再决定是否删除。',
          toolCalls: [
            {
              id: 't-1',
              toolName: 'canvas.find_items',
              status: 'completed',
              args: { query: '开场' },
              result: { items: [{ id: 'item-1' }] }
            }
          ]
        },
        {
          id: 'i-1',
          type: 'interrupt_card',
          interrupt: {
            interruptId: 'interrupt-1',
            kind: 'confirm_execute',
            title: '确认执行',
            message: '请选择模型后继续',
            selectedModelId: '',
            modelOptions: [
              { modelId: 'model-a', label: '模型 A', resolution: '1024x1024' }
            ],
            actions: ['approve', 'reject']
          }
        }
      ])
    })

    const wrapper = mount(CanvasAssistant, {
      props: {
        documentId: 'doc-1'
      }
    })

    expect(wrapper.attributes('style')).toContain('user-select: text')
    expect(wrapper.text()).toContain('AI 助手')
    expect(wrapper.text()).toContain('Session session-1')
    expect(wrapper.text()).toContain('请看一下')
    expect(wrapper.text()).toContain('先定位开场节点，再决定是否删除。')
    expect(wrapper.text()).toContain('canvas.find_items')
    expect(wrapper.text()).toContain('确认执行')
    expect(wrapper.find('[data-testid="assistant-api-key-select"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="assistant-chat-model-select"]').exists()).toBe(true)

    await wrapper.find('textarea').setValue('请删除开场节点')
    await wrapper.find('form').trigger('submit.prevent')
    expect(sendMessage).toHaveBeenCalledWith('请删除开场节点')

    await wrapper.find('select').setValue('model-a')
    expect(updatePendingConfirmationModelId).toHaveBeenCalledWith('model-a')

    await wrapper.find('.assistant-confirmation__button--primary').trigger('click')
    expect(resumeConfirmation).toHaveBeenCalledWith({
      decision: 'approve',
      selectedModelId: 'model-a'
    })

    await wrapper.find('.assistant-header__reset').trigger('click')
    expect(reset).toHaveBeenCalled()
  })

  it('renders streaming progress in timeline footer instead of animating header shell', () => {
    useCanvasAssistant.mockReturnValue({
      sessionId: ref('session-stream'),
      status: ref('streaming'),
      error: ref(''),
      eventLog: ref([]),
      messages: ref([]),
      pendingInterrupt: ref(null),
      apiKeyOptions: ref([{ id: 'key-1', label: '主 Key', provider: 'openai' }]),
      chatModelOptions: ref(['gpt-4o-mini']),
      selectedApiKeyId: ref('key-1'),
      selectedChatModelId: ref('gpt-4o-mini'),
      apiKeysLoading: ref(false),
      chatModelsLoading: ref(false),
      isStreaming: ref(true),
      canSend: ref(false),
      sendMessage: vi.fn(),
      updateSelectedApiKeyId: vi.fn(),
      updateSelectedChatModelId: vi.fn(),
      resumeInterrupt: vi.fn(),
      updatePendingInterruptModelId: vi.fn(),
      reset: vi.fn()
    })

    useCanvasAssistantTimeline.mockReturnValue({
      timelineItems: computed(() => [])
    })

    const wrapper = mount(CanvasAssistant, {
      props: {
        documentId: 'doc-1'
      }
    })

    expect(wrapper.find('.assistant-timeline__loading').exists()).toBe(true)
    expect(wrapper.find('.assistant-timeline__loading-ring').exists()).toBe(true)
    expect(wrapper.find('[data-testid="assistant-stream-indicator"]').exists()).toBe(true)
    expect(wrapper.find('.assistant-header').classes()).not.toContain('assistant-header--streaming')
  })
})
