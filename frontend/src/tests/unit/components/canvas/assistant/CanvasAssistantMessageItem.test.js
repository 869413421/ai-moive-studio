/**
 * @vitest-environment jsdom
 */

import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import CanvasAssistantMessageItem from '@/components/canvas/assistant/CanvasAssistantMessageItem.vue'

describe('CanvasAssistantMessageItem', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('reveals assistant streaming content with a typewriter-like progression', async () => {
    vi.useFakeTimers()

    const wrapper = mount(CanvasAssistantMessageItem, {
      props: {
        message: { role: 'assistant', content: '正在生成关键帧和视频。' },
        streaming: true,
        live: true
      }
    })

    expect(wrapper.text()).not.toContain('正在生成关键帧和视频。')

    await vi.runAllTimersAsync()

    expect(wrapper.text()).toContain('正在生成关键帧和视频。')
    expect(wrapper.find('.assistant-message__cursor').exists()).toBe(true)
    expect(wrapper.find('.assistant-message__wave').exists()).toBe(true)
  })

  it('still animates the latest assistant reply when the backend emits a completed message in one shot', async () => {
    vi.useFakeTimers()

    const wrapper = mount(CanvasAssistantMessageItem, {
      props: {
        message: { role: 'assistant', content: '' },
        streaming: false
      }
    })

    await wrapper.setProps({
      message: { role: 'assistant', content: '已基于剧本准备角色三视图与分镜。' },
      streaming: false
    })

    expect(wrapper.text()).not.toContain('已基于剧本准备角色三视图与分镜。')

    await vi.runAllTimersAsync()

    expect(wrapper.text()).toContain('已基于剧本准备角色三视图与分镜。')
  })

  it('does not render wave for non-live assistant messages or user messages', () => {
    const assistantWrapper = mount(CanvasAssistantMessageItem, {
      props: {
        message: { role: 'assistant', content: '历史消息' },
        streaming: false
      }
    })
    const userWrapper = mount(CanvasAssistantMessageItem, {
      props: {
        message: { role: 'user', content: '你好' },
        streaming: true
      }
    })

    expect(assistantWrapper.find('.assistant-message__wave').exists()).toBe(false)
    expect(userWrapper.find('.assistant-message__wave').exists()).toBe(false)
  })

  it('renders no empty placeholder copy for a live assistant placeholder bubble', () => {
    const wrapper = mount(CanvasAssistantMessageItem, {
      props: {
        message: { role: 'assistant', content: '' },
        streaming: true,
        live: true
      }
    })

    expect(wrapper.text()).not.toContain('（空消息）')
    expect(wrapper.find('.assistant-message__wave').exists()).toBe(true)
  })
})
