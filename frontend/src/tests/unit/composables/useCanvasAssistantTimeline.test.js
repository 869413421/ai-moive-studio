/**
 * @vitest-environment jsdom
 */

import { describe, expect, it } from 'vitest'
import { buildCanvasAssistantTimelineItems, reduceCanvasAssistantEventLog } from '@/composables/useCanvasAssistantTimeline'

describe('useCanvasAssistantTimeline', () => {
  it('builds old-style timeline items from eventLog reducer source', () => {
    const items = buildCanvasAssistantTimelineItems({
      eventLog: [
        { kind: 'message', message: { id: 'm-1', role: 'user', content: '删除开场节点', order: 1 } },
        { kind: 'thinking', thinking: { content: '先定位开场节点。', order: 2 } },
        {
          kind: 'tool',
          toolCall: {
            id: 'call-1',
            toolName: 'canvas.find_items',
            status: 'completed',
            args: { query: '开场节点' },
            result: { ok: true },
            order: 2
          }
        },
        {
          kind: 'interrupt',
          interrupt: {
            interruptId: 'interrupt-1',
            kind: 'confirm_delete',
            title: '确认删除',
            message: '这是高风险动作',
            order: 3
          }
        },
        { kind: 'message_completed', message: { id: 'm-2', role: 'assistant', content: '需要确认后继续。', order: 4 } },
        { kind: 'error', message: 'stream closed unexpectedly' }
      ]
    })

    expect(items.map((item) => item.type)).toEqual([
      'user_message',
      'tool_summary',
      'assistant_message',
      'interrupt_card',
      'error_notice'
    ])
    expect(items[1]).toMatchObject({
      thinkingBuffer: '先定位开场节点。',
      toolCalls: [{ toolName: 'canvas.find_items' }]
    })
  })

  it('reduces finalized message, tool summary, interrupt and refresh request from eventLog', () => {
    const items = buildCanvasAssistantTimelineItems({
      eventLog: [
        { kind: 'message', message: { id: 'm-1', role: 'user', content: '更新一下', order: 1 } },
        { kind: 'thinking', thinking: { content: '准备批量更新节点。', order: 2 } },
        {
          kind: 'tool',
          toolCall: {
            id: 'tool-1',
            toolName: 'canvas.update_items',
            status: 'completed',
            order: 3,
            result: {
              effect: { needs_refresh: true, refresh_scopes: ['document'] }
            }
          }
        },
        {
          kind: 'interrupt',
          interrupt: {
            interruptId: 'interrupt-1',
            kind: 'confirm_execute',
            title: '确认执行',
            order: 5
          }
        },
        { kind: 'interrupt_resolved', interrupt: { interruptId: 'interrupt-1', decision: 'approve' } },
        { kind: 'message_completed', message: { id: 'm-2', role: 'assistant', content: '已完成', order: 4 } }
      ],
    })

    expect(items.map((item) => item.type)).toEqual([
      'user_message',
      'tool_summary',
      'assistant_message',
    ])
    expect(items[1]).toMatchObject({
      type: 'tool_summary',
      thinkingBuffer: '准备批量更新节点。',
      toolCalls: [{ id: 'tool-1', toolName: 'canvas.update_items' }]
    })
  })

  it('uses top-level tool effect to derive refresh requests', async () => {
    const reduced = reduceCanvasAssistantEventLog({
      eventLog: [
        {
          kind: 'tool',
          toolCall: {
            id: 'tool-9',
            toolName: 'canvas.create_item',
            status: 'completed',
            result: { ok: true },
            effect: { mutated: true, needs_refresh: true, refresh_scopes: ['document'] }
          }
        }
      ]
    })

    expect(reduced.refreshRequest).toEqual({
      scopes: ['document'],
      effect: { mutated: true, needs_refresh: true, refresh_scopes: ['document'] }
    })
  })

  it('keeps streaming status while a turn is active so UI animations can render', () => {
    const reduced = reduceCanvasAssistantEventLog({
      eventLog: [
        { kind: 'session', sessionId: 'session-1' },
        { kind: 'thinking', thinking: { content: '先检查剧本，再决定是否拆分分镜。' } },
        {
          kind: 'tool',
          toolCall: {
            id: 'tool-1',
            toolName: 'canvas.find_items',
            status: 'requested',
            args: { query: '剧本' }
          }
        }
      ]
    })

    expect(reduced.status).toBe('streaming')
    expect(reduced.isStreaming).toBe(true)
    expect(reduced.activeTool).toBe('canvas.find_items')
    expect(reduced.thinkingBuffer).toBe('先检查剧本，再决定是否拆分分镜。')
  })
})
