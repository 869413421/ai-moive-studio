import { onBeforeUnmount, reactive } from 'vue'
import { canvasService } from '@/services/canvas'

const WAITING_RUN_STATUSES = new Set(['pending', 'processing', 'running', 'queued', 'submitted'])
const normalizeRunStatus = (status, fallback = 'processing') => {
  const normalized = String(status || '').trim().toLowerCase()
  if (WAITING_RUN_STATUSES.has(normalized)) {
    return normalized === 'running' ? 'processing' : normalized
  }
  if (normalized === 'completed' || normalized === 'failed') {
    return normalized
  }
  return fallback
}

const isWaitingRunStatus = (status) => WAITING_RUN_STATUSES.has(String(status || '').trim().toLowerCase())

const applyGenerationResultToContent = (itemType, currentContent = {}, resultPayload = {}) => {
  const nextContent = { ...currentContent }
  if (itemType === 'text' && resultPayload.text) {
    nextContent.text = resultPayload.text
  }
  if (itemType === 'image' && resultPayload.result_image_url) {
    nextContent.result_image_url = resultPayload.result_image_url
  }
  if (itemType === 'video' && resultPayload.result_video_url) {
    nextContent.result_video_url = resultPayload.result_video_url
  }
  if (resultPayload.provider_task_id) {
    nextContent.provider_task_id = resultPayload.provider_task_id
  }
  if (resultPayload.task_id) {
    nextContent.task_id = resultPayload.task_id
  }
  return nextContent
}

export function useCanvasGeneration(updateItem) {
  const state = reactive({
    loadingByItem: {},
    histories: {},
    historyLoadingByItem: {},
    streamControllersByItem: {}
  })

  const setLoading = (itemId, value) => {
    state.loadingByItem[itemId] = value
  }

  const clearStream = (itemId) => {
    const controller = state.streamControllersByItem[itemId]
    if (controller) {
      controller.abort()
      delete state.streamControllersByItem[itemId]
    }
  }

  const loadHistory = async (itemId) => {
    state.historyLoadingByItem[itemId] = true
    try {
      const response = await canvasService.listGenerations(itemId, { page: 1, size: 20 })
      state.histories[itemId] = response.generations || []
      return state.histories[itemId]
    } catch {
      state.histories[itemId] = []
      return state.histories[itemId]
    } finally {
      state.historyLoadingByItem[itemId] = false
    }
  }

  const syncItemFromGeneration = (item, generation) => {
    updateItem(item.id, {
      content: applyGenerationResultToContent(item.item_type, item.content, generation.result_payload || {}),
      last_run_status: generation.status,
      last_run_error: generation.error_message || null,
      last_output: generation.result_payload || {},
      is_persisted: true
    })
  }

  const parseSseBlock = (block) => {
    const lines = block
      .split(/\r?\n/)
      .map((line) => line.trimEnd())
      .filter(Boolean)
    let event = 'message'
    const dataLines = []

    lines.forEach((line) => {
      if (line.startsWith('event:')) {
        event = line.slice(6).trim()
        return
      }
      if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).trim())
      }
    })

    if (!dataLines.length) {
      return null
    }

    try {
      return {
        event,
        data: JSON.parse(dataLines.join('\n'))
      }
    } catch {
      return null
    }
  }

  const processSseBuffer = (buffer, onEvent) => {
    let nextBuffer = buffer
    while (true) {
      const separatorIndex = nextBuffer.indexOf('\n\n')
      if (separatorIndex < 0) {
        break
      }
      const block = nextBuffer.slice(0, separatorIndex)
      nextBuffer = nextBuffer.slice(separatorIndex + 2)
      const parsed = parseSseBlock(block)
      if (parsed) {
        onEvent(parsed)
      }
    }
    return nextBuffer
  }

  const streamTextGeneration = async (item, payload = {}) => {
    clearStream(item.id)
    setLoading(item.id, true)

    const controller = new AbortController()
    state.streamControllersByItem[item.id] = controller
    const decoder = new TextDecoder()
    let finalEvent = null

    try {
      const response = await canvasService.generateTextStream(item.id, payload, {
        signal: controller.signal
      })
      if (!response.ok) {
        const errorText = await response.text()
        throw new Error(errorText || '文本生成提交失败')
      }
      if (!response.body) {
        throw new Error('文本生成流不可用')
      }

      const reader = response.body.getReader()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) {
          break
        }
        buffer += decoder.decode(value, { stream: true })
        buffer = processSseBuffer(buffer, ({ event, data }) => {
          if (event === 'start') {
            updateItem(item.id, {
              last_run_status: normalizeRunStatus(data.status, 'processing'),
              last_run_error: null
            }, { persist: false })
            return
          }

          if (event === 'delta') {
            updateItem(item.id, {
              content: {
                text: data.text || ''
              },
              last_run_status: normalizeRunStatus(data.status, 'processing'),
              last_run_error: null
            }, { persist: false })
            return
          }

          if (event === 'complete') {
            finalEvent = data
            state.histories[item.id] = [
              data.generation,
              ...(state.histories[item.id] || []).filter((entry) => entry.id !== data.generation?.id)
            ].filter(Boolean)
            updateItem(item.id, {
              content: data.item?.content || { text: data.text || '' },
              generation_config: data.item?.generation_config || item.generation_config,
              last_run_status: 'completed',
              last_run_error: null,
              last_output: data.item?.last_output || data.generation?.result_payload || { text: data.text || '' },
              is_persisted: true
            })
            return
          }

          if (event === 'fail') {
            throw new Error(data.error_message || '文本生成失败')
          }
        })
      }

      if (!finalEvent) {
        throw new Error('文本生成流提前结束')
      }

      return {
        message: '文本生成完成',
        item: finalEvent.item,
        generation: finalEvent.generation
      }
    } catch (error) {
      if (error?.name !== 'AbortError') {
        updateItem(item.id, {
          last_run_status: 'failed',
          last_run_error: error?.message || '文本生成失败'
        })
      }
      throw error
    } finally {
      if (state.streamControllersByItem[item.id] === controller) {
        delete state.streamControllersByItem[item.id]
      }
      setLoading(item.id, false)
    }
  }

  const streamMediaGeneration = async (item, payload = {}) => {
    clearStream(item.id)
    setLoading(item.id, true)

    const controller = new AbortController()
    state.streamControllersByItem[item.id] = controller
    const decoder = new TextDecoder()
    let finalEvent = null

    try {
      const response = item.item_type === 'image'
        ? await canvasService.generateImageStream(item.id, payload, { signal: controller.signal })
        : await canvasService.generateVideoStream(item.id, payload, { signal: controller.signal })

      if (!response.ok) {
        const errorText = await response.text()
        throw new Error(errorText || `${item.item_type === 'image' ? '图片' : '视频'}生成提交失败`)
      }
      if (!response.body) {
        throw new Error(`${item.item_type === 'image' ? '图片' : '视频'}生成流不可用`)
      }

      const reader = response.body.getReader()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) {
          break
        }
        buffer += decoder.decode(value, { stream: true })
        buffer = processSseBuffer(buffer, ({ event, data }) => {
          if (event === 'start') {
            updateItem(item.id, {
              last_run_status: normalizeRunStatus(data.status, 'processing'),
              last_run_error: null
            }, { persist: false })
            return
          }

          if (event === 'progress') {
            const nextStatus = normalizeRunStatus(data.status, item.last_run_status || 'processing')
            updateItem(item.id, {
              content: applyGenerationResultToContent(item.item_type, item.content, {
                provider_task_id: data.provider_task_id,
                task_id: data.generation_id
              }),
              last_run_status: nextStatus,
              last_run_error: null,
              last_output: data.provider_payload || item.last_output || {}
            }, { persist: false })
            return
          }

          if (event === 'complete') {
            finalEvent = data
            state.histories[item.id] = [
              data.generation,
              ...(state.histories[item.id] || []).filter((entry) => entry.id !== data.generation?.id)
            ].filter(Boolean)
            updateItem(item.id, {
              content: data.item?.content || applyGenerationResultToContent(item.item_type, item.content, data.generation?.result_payload || {}),
              generation_config: data.item?.generation_config || item.generation_config,
              last_run_status: 'completed',
              last_run_error: null,
              last_output: data.item?.last_output || data.generation?.result_payload || {},
              is_persisted: true
            })
            return
          }

          if (event === 'fail') {
            if (isWaitingRunStatus(data.status) || data.transient_status_issue === true) {
              updateItem(item.id, {
                last_run_status: normalizeRunStatus(data.status, item.last_run_status || 'processing'),
                last_run_error: null,
                last_output: data.provider_payload || item.last_output || {}
              }, { persist: false })
              return
            }
            throw new Error(data.error_message || `${item.item_type === 'image' ? '图片' : '视频'}生成失败`)
          }
        })
      }

      if (!finalEvent) {
        throw new Error(`${item.item_type === 'image' ? '图片' : '视频'}生成流提前结束`)
      }

      return {
        message: `${item.item_type === 'image' ? '图片' : '视频'}生成完成`,
        item: finalEvent.item,
        generation: finalEvent.generation
      }
    } catch (error) {
      if (error?.name !== 'AbortError') {
        updateItem(item.id, {
          last_run_status: 'failed',
          last_run_error: error?.message || `${item.item_type === 'image' ? '图片' : '视频'}生成失败`
        })
      }
      throw error
    } finally {
      if (state.streamControllersByItem[item.id] === controller) {
        delete state.streamControllersByItem[item.id]
      }
      setLoading(item.id, false)
    }
  }

  const generate = async (item, payload = {}) => {
    if (item.item_type === 'text') {
      return streamTextGeneration(item, payload)
    }
    return streamMediaGeneration(item, payload)
  }

  const applyGeneration = async (itemId, generationId) => {
    const response = await canvasService.applyGeneration(itemId, generationId)
    updateItem(itemId, {
      content: response.item.content,
      generation_config: response.item.generation_config,
      last_run_status: response.item.last_run_status,
      last_run_error: response.item.last_run_error,
      last_output: response.item.last_output,
      is_persisted: true
    })
    await loadHistory(itemId)
    return response
  }

  onBeforeUnmount(() => {
    Object.keys(state.streamControllersByItem).forEach(clearStream)
  })

  return {
    generationLoadingByItem: state.loadingByItem,
    generationHistories: state.histories,
    historyLoadingByItem: state.historyLoadingByItem,
    loadHistory,
    generate,
    applyGeneration,
    clearStream
  }
}
