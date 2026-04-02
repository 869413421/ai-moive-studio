import { computed, ref } from 'vue'
import { canvasService } from '@/services/canvas'

const DEFAULT_CONTENT = {
  text: () => ({ text: '', text_preview: '', prompt: '', promptTokens: [] }),
  image: () => ({ prompt: '', result_image_url: '', reference_image_url: '', style_reference_image_object_key: '', promptTokens: [] }),
  video: () => ({ prompt: '', result_video_url: '', reference_image_urls: [], reference_text_ids: [], promptTokens: [] })
}

const DEFAULT_SIZE = {
  text: { width: 320, height: 220 },
  image: { width: 340, height: 280 },
  video: { width: 360, height: 300 }
}

const PERSIST_DEBOUNCE_MS = 300
const MEDIA_URL_TO_OBJECT_KEY_FIELDS = {
  result_image_url: 'result_image_object_key',
  reference_image_url: 'reference_image_object_key',
  result_video_url: 'result_video_object_key'
}

const stripTransientMediaUrls = (payload = {}) => {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return payload
  }

  const sanitized = { ...payload }
  Object.entries(MEDIA_URL_TO_OBJECT_KEY_FIELDS).forEach(([urlField, objectKeyField]) => {
    if (sanitized[objectKeyField]) {
      delete sanitized[urlField]
    }
  })
  return sanitized
}

export function useCanvasEditor() {
  const loading = ref(false)
  const saving = ref(false)
  const document = ref(null)
  const items = ref([])
  const connections = ref([])
  const selectedItemId = ref(null)
  const dirty = ref(false)
  const zoom = ref(1)
  const pan = ref({ x: 0, y: 0 })
  const pendingConnection = ref(null)

  let currentDocumentId = ''
  const persistTimers = new Map()
  const detailLoading = new Set()

  const selectedItem = computed(() =>
    items.value.find((item) => item.id === selectedItemId.value) || null
  )

  const maxZIndex = computed(() =>
    items.value.reduce((max, item) => Math.max(max, item.z_index || 0), 0)
  )

  const normalizeItem = (item) => ({
    id: item.id,
    item_type: item.item_type,
    title: item.title || '',
    position_x: Number(item.position_x || 0),
    position_y: Number(item.position_y || 0),
    width: Number(item.width || DEFAULT_SIZE[item.item_type]?.width || 320),
    height: Number(item.height || DEFAULT_SIZE[item.item_type]?.height || 220),
    z_index: Number(item.z_index || 0),
    content: { ...(DEFAULT_CONTENT[item.item_type]?.() || {}), ...(item.content || {}) },
    generation_config: { ...(item.generation_config || {}) },
    last_run_status: item.last_run_status || 'idle',
    last_run_error: item.last_run_error || null,
    last_output: { ...(item.last_output || {}) },
    has_detail: Boolean(item.has_detail || item.content?.text || item.content?.prompt || item.content?.promptTokens?.length),
    is_persisted: true
  })

  const normalizeConnection = (connection) => ({
    id: connection.id,
    source_item_id: connection.source_item_id,
    target_item_id: connection.target_item_id,
    source_handle: connection.source_handle,
    target_handle: connection.target_handle
  })

  const mergeItem = (itemId, patch) => {
    items.value = items.value.map((item) =>
      item.id === itemId
        ? {
          ...item,
          ...patch,
          content: patch.content ? { ...item.content, ...patch.content } : item.content,
          generation_config: patch.generation_config ? { ...item.generation_config, ...patch.generation_config } : item.generation_config,
          last_output: patch.last_output ? { ...item.last_output, ...patch.last_output } : item.last_output
        }
        : item
    )
  }

  const clearPersistTimer = (itemId) => {
    const timer = persistTimers.get(itemId)
    if (timer) {
      window.clearTimeout(timer)
      persistTimers.delete(itemId)
    }
  }

  const persistItemNow = async (itemId) => {
    clearPersistTimer(itemId)
    if (!currentDocumentId) return
    const item = items.value.find((entry) => entry.id === itemId)
    if (!item?.is_persisted) return

    await canvasService.updateItem(currentDocumentId, itemId, {
      title: item.title,
      position_x: item.position_x,
      position_y: item.position_y,
      width: item.width,
      height: item.height,
      z_index: item.z_index,
      content: stripTransientMediaUrls(item.content),
      generation_config: item.generation_config,
      last_run_status: item.last_run_status,
      last_run_error: item.last_run_error,
      last_output: stripTransientMediaUrls(item.last_output)
    })
  }

  const schedulePersist = (itemId) => {
    if (!currentDocumentId) return
    clearPersistTimer(itemId)
    const timer = window.setTimeout(async () => {
      try {
        await persistItemNow(itemId)
        dirty.value = persistTimers.size > 0
      } catch (error) {
        console.error('Persist canvas item failed', error)
      }
    }, PERSIST_DEBOUNCE_MS)
    persistTimers.set(itemId, timer)
    dirty.value = true
  }

  const hydrateItemDetail = async (itemId) => {
    if (!currentDocumentId || !itemId || detailLoading.has(itemId)) return
    const target = items.value.find((item) => item.id === itemId)
    if (!target || target.has_detail) return

    detailLoading.add(itemId)
    try {
      const detail = normalizeItem(await canvasService.getItem(currentDocumentId, itemId))
      mergeItem(itemId, {
        ...detail,
        has_detail: true
      })
    } finally {
      detailLoading.delete(itemId)
    }
  }

  const loadDocument = async (documentId) => {
    loading.value = true
    currentDocumentId = documentId
    try {
      const snapshot = await canvasService.getLite(documentId)
      document.value = snapshot.document
      items.value = (snapshot.items || []).map((item) => normalizeItem({ ...item, has_detail: false }))
      connections.value = (snapshot.connections || []).map(normalizeConnection)
      selectedItemId.value = items.value[0]?.id || null
      dirty.value = false
      if (selectedItemId.value) {
        await hydrateItemDetail(selectedItemId.value)
      }
    } finally {
      loading.value = false
    }
  }

  const save = async () => {
    saving.value = true
    try {
      const itemIds = [...persistTimers.keys()]
      for (const itemId of itemIds) {
        await persistItemNow(itemId)
      }
      dirty.value = false
      return { document: document.value, items: items.value, connections: connections.value }
    } finally {
      saving.value = false
    }
  }

  const createItem = async (itemType, position = {}) => {
    if (!currentDocumentId) return null
    const count = items.value.filter((item) => item.item_type === itemType).length
    const size = DEFAULT_SIZE[itemType] || DEFAULT_SIZE.text
    const payload = {
      item_type: itemType,
      title:
        itemType === 'text' ? `文本节点 ${count + 1}` :
          itemType === 'image' ? `图片节点 ${count + 1}` :
            `视频节点 ${count + 1}`,
      position_x: Number(position.position_x ?? (120 + count * 24)),
      position_y: Number(position.position_y ?? (120 + count * 24)),
      width: size.width,
      height: size.height,
      z_index: maxZIndex.value + 1,
      content: DEFAULT_CONTENT[itemType](),
      generation_config: {},
      last_run_status: 'idle',
      last_run_error: null,
      last_output: {}
    }
    const created = normalizeItem(await canvasService.createItem(currentDocumentId, payload))
    items.value = [...items.value, { ...created, has_detail: true }]
    selectedItemId.value = created.id
    return created
  }

  const updateItem = (itemId, patch, options = {}) => {
    mergeItem(itemId, patch)
    if (options.persist === false) {
      return
    }
    schedulePersist(itemId)
  }

  const removeItem = async (itemId) => {
    if (!currentDocumentId) return
    clearPersistTimer(itemId)
    await canvasService.deleteItem(currentDocumentId, itemId)
    items.value = items.value.filter((item) => item.id !== itemId)
    connections.value = connections.value.filter(
      (connection) => connection.source_item_id !== itemId && connection.target_item_id !== itemId
    )
    if (selectedItemId.value === itemId) {
      selectedItemId.value = items.value[0]?.id || null
      if (selectedItemId.value) {
        void hydrateItemDetail(selectedItemId.value)
      }
    }
    if (pendingConnection.value?.itemId === itemId) {
      pendingConnection.value = null
    }
  }

  const setSelection = (itemId) => {
    selectedItemId.value = itemId
    void hydrateItemDetail(itemId)
  }

  const clearSelection = () => {
    selectedItemId.value = null
  }

  const startConnection = (itemId, handle = 'output') => {
    pendingConnection.value = { itemId, handle }
    setSelection(itemId)
  }

  const completeConnection = async (itemId, handle = 'input') => {
    if (!pendingConnection.value || !currentDocumentId) return
    if (pendingConnection.value.itemId === itemId) {
      pendingConnection.value = null
      return
    }

    const exists = connections.value.some(
      (connection) =>
        connection.source_item_id === pendingConnection.value.itemId &&
        connection.target_item_id === itemId &&
        connection.source_handle === pendingConnection.value.handle &&
        connection.target_handle === handle
    )

    if (!exists) {
      const created = normalizeConnection(await canvasService.createConnection(currentDocumentId, {
        source_item_id: pendingConnection.value.itemId,
        target_item_id: itemId,
        source_handle: pendingConnection.value.handle,
        target_handle: handle
      }))
      connections.value = [...connections.value, created]
    }

    pendingConnection.value = null
  }

  const removeConnection = async (connectionId) => {
    if (!currentDocumentId) return
    await canvasService.deleteConnection(currentDocumentId, connectionId)
    connections.value = connections.value.filter((connection) => connection.id !== connectionId)
  }

  const updateViewport = ({ zoom: nextZoom = zoom.value, pan: nextPan = pan.value }) => {
    zoom.value = Math.min(2, Math.max(0.5, Number(nextZoom)))
    pan.value = {
      x: Number(nextPan.x || 0),
      y: Number(nextPan.y || 0)
    }
  }

  return {
    loading,
    saving,
    document,
    items,
    connections,
    selectedItemId,
    selectedItem,
    dirty,
    zoom,
    pan,
    pendingConnection,
    loadDocument,
    save,
    createItem,
    updateItem,
    removeItem,
    setSelection,
    clearSelection,
    startConnection,
    completeConnection,
    removeConnection,
    updateViewport
  }
}
