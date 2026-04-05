/**
 * @vitest-environment jsdom
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'

const encoder = new TextEncoder()

const createStreamResponse = (chunks, headers = {}) => {
  const queue = chunks.map((chunk) => encoder.encode(chunk))
  return {
    ok: true,
    status: 200,
    headers: {
      get: (name) => headers[String(name || '').toLowerCase()] || ''
    },
    body: {
      getReader: () => ({
        read: vi.fn(async () => {
          if (!queue.length) {
            return { done: true, value: undefined }
          }
          return { done: false, value: queue.shift() }
        }),
        releaseLock: vi.fn()
      })
    }
  }
}

describe('canvas assistant service', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.clearAllMocks()
    global.fetch = vi.fn()
  })

  it('normalizes new agent protocol events from chat', async () => {
    global.fetch.mockResolvedValueOnce(
      createStreamResponse([
        'data: {"type":"agent.session.started","data":{"session_id":"session-1"}}\n\n',
        'data: {"type":"agent.tool.call","data":{"id":"tool-1","tool_name":"canvas.find_items","args":{"query":"开场"}}}\n\n',
        'data: {"type":"agent.message.completed","data":{"id":"assistant-1","role":"assistant","content":"我找到了候选节点。"}}\n\n',
        'data: {"type":"agent.interrupt.requested","data":{"session_id":"session-1","interrupt_id":"interrupt-1","kind":"confirm_delete","title":"确认删除","message":"请选择后继续","actions":["approve","reject"]}}\n\n',
        'data: {"type":"agent.done","data":{"session_id":"session-1"}}\n\n'
      ])
    )

    const { canvasAssistantService } = await import('@/services/canvasAssistant')

    const events = []
    await canvasAssistantService.chat(
      {
        documentId: 'doc-1',
        message: '删除开场节点'
      },
      {
        onEvent: (event) => events.push(event)
      }
    )

    expect(JSON.parse(global.fetch.mock.calls[0][1].body)).toEqual({
      document_id: 'doc-1',
      message: '删除开场节点'
    })
    expect(events[0]).toMatchObject({ kind: 'session', sessionId: 'session-1' })
    expect(events[1]).toMatchObject({
      kind: 'tool',
      toolCall: { id: 'tool-1', toolName: 'canvas.find_items' }
    })
    expect(events[2]).toMatchObject({
      kind: 'message_completed',
      message: { id: 'assistant-1', role: 'assistant', content: '我找到了候选节点。' }
    })
    expect(events[3]).toMatchObject({
      kind: 'interrupt',
      interrupt: {
        interruptId: 'interrupt-1',
        kind: 'confirm_delete'
      }
    })
    expect(events[4]).toMatchObject({ kind: 'done' })
  })

  it('preserves top-level effect from agent.tool.result events', async () => {
    global.fetch.mockResolvedValueOnce(
      createStreamResponse([
        'data: {"type":"agent.tool.result","data":{"id":"tool-9","tool_name":"canvas.create_item","status":"completed","result":{"ok":true},"effect":{"mutated":true,"needs_refresh":true,"refresh_scopes":["document"]}}}\n\n'
      ])
    )

    const { canvasAssistantService } = await import('@/services/canvasAssistant')

    const events = []
    await canvasAssistantService.chat(
      {
        documentId: 'doc-1',
        message: '创建一个文本节点'
      },
      {
        onEvent: (event) => events.push(event)
      }
    )

    expect(events[0]).toMatchObject({
      kind: 'tool',
      toolCall: {
        id: 'tool-9',
        toolName: 'canvas.create_item',
        effect: {
          mutated: true,
          needs_refresh: true,
          refresh_scopes: ['document']
        }
      }
    })
  })

  it('posts resume payloads using interrupt decision fields', async () => {
    global.fetch.mockResolvedValueOnce(
      createStreamResponse([
        'data: {"type":"agent.interrupt.resolved","data":{"interrupt_id":"interrupt-1","decision":"approve"}}\n\n',
        'data: {"type":"agent.done","data":{"session_id":"session-1"}}\n\n'
      ])
    )

    const { canvasAssistantService } = await import('@/services/canvasAssistant')

    await canvasAssistantService.resume({
      documentId: 'doc-1',
      sessionId: 'session-1',
      interruptId: 'interrupt-1',
      decision: 'approve',
      selectedModelId: 'model-a'
    })

    expect(JSON.parse(global.fetch.mock.calls[0][1].body)).toEqual({
      document_id: 'doc-1',
      session_id: 'session-1',
      interrupt_id: 'interrupt-1',
      decision: 'approve',
      selected_model_id: 'model-a'
    })
  })
})
