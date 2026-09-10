/**
 * @vitest-environment jsdom
 */

import { nextTick, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ElMessage, ElMessageBox } from 'element-plus'
import CanvasEditor from '@/views/canvas/CanvasEditor.vue'
import { useCanvasEditor } from '@/composables/useCanvasEditor'
import { useCanvasGeneration } from '@/composables/useCanvasGeneration'

vi.mock('@/composables/useCanvasEditor', () => ({
  useCanvasEditor: vi.fn(),
  default: vi.fn()
}))

vi.mock('@/composables/useCanvasGeneration', () => ({
  useCanvasGeneration: vi.fn(),
  default: vi.fn()
}))

vi.mock('@/services/apiKeys', () => ({
  apiKeysService: {
    getAPIKeys: vi.fn().mockResolvedValue({ api_keys: [] })
  }
}))

vi.mock('@/services/canvas', () => ({
  canvasService: {
    getModelCatalog: vi.fn().mockResolvedValue({ connections: {} }),
    uploadVideo: vi.fn()
  }
}))

vi.mock('@/services/upload', () => ({
  fileService: {
    uploadFile: vi.fn()
  }
}))

vi.mock('@/components/canvas/assistant/CanvasAssistant.vue', () => ({
  default: {
    name: 'CanvasAssistant',
    props: ['documentId', 'refreshCanvas'],
    template: '<div class="assistant-stub"></div>'
  }
}))

describe('CanvasEditor assistant wiring', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('passes the current document id to the assistant rail without editor selection coupling', async () => {
    const selectedItem = ref({
      id: 'item-1',
      item_type: 'text',
      title: '文本节点 1',
      position_x: 20,
      position_y: 30,
      width: 320,
      height: 220,
      z_index: 1,
      content: { text: 'hello', promptTokens: [] },
      generation_config: {},
      last_run_status: 'idle',
      last_run_error: null,
      last_output: {},
      has_detail: true,
      is_persisted: true
    })

    useCanvasEditor.mockReturnValue({
      loading: ref(false),
      saving: ref(false),
      document: ref({ id: 'doc-1', title: 'Canvas Doc' }),
      items: ref([selectedItem.value]),
      connections: ref([]),
      selectedItemIds: ref(['item-1']),
      selectedItemId: ref('item-1'),
      selectedItem,
      zoom: ref(1),
      pan: ref({ x: 0, y: 0 }),
      dirty: ref(false),
      loadDocument: vi.fn(),
      save: vi.fn(),
      createItem: vi.fn(),
      updateItem: vi.fn(),
      removeItem: vi.fn(),
      removeItems: vi.fn(),
      setSelection: vi.fn(),
      setSelections: vi.fn(),
      clearSelection: vi.fn(),
      startConnection: vi.fn(),
      completeConnection: vi.fn(),
      removeConnection: vi.fn(),
      updateViewport: vi.fn()
    })

    useCanvasGeneration.mockReturnValue({
      generationLoadingByItem: {},
      generationHistories: {},
      historyLoadingByItem: {},
      loadHistory: vi.fn(),
      generate: vi.fn(),
      applyGeneration: vi.fn()
    })

    const wrapper = mount(CanvasEditor, {
      global: {
        directives: {
          loading: {
            mounted() {},
            updated() {}
          }
        },
        stubs: {
          CanvasConnectionActions: true,
          CanvasGenerationHistoryDrawer: true,
          CanvasImageStudio: true,
          CanvasLinkCreateMenu: true,
          CanvasLinkDragOverlay: true,
          CanvasWorkbenchLayout: {
            name: 'CanvasWorkbenchLayout',
            template: '<div class="workbench-stub"><slot /></div>'
          },
          CanvasTextStudio: true,
          CanvasVideoStudio: true,
          KonvaCanvasStage: true
        }
      }
    })

    const assistant = wrapper.findComponent({ name: 'CanvasAssistant' })
    expect(assistant.exists()).toBe(true)
    expect(assistant.props('documentId')).toBe('doc-1')

    selectedItem.value = null
    await nextTick()

    expect(assistant.props('documentId')).toBe('doc-1')
    wrapper.unmount()
  })

  it('shows the pan and marquee gesture hint in the workbench chrome', async () => {
    useCanvasEditor.mockReturnValue({
      loading: ref(false),
      saving: ref(false),
      document: ref({ id: 'doc-1', title: 'Canvas Doc' }),
      items: ref([]),
      connections: ref([]),
      selectedItemIds: ref([]),
      selectedItemId: ref(null),
      selectedItem: ref(null),
      zoom: ref(1),
      pan: ref({ x: 0, y: 0 }),
      dirty: ref(false),
      loadDocument: vi.fn(),
      save: vi.fn(),
      createItem: vi.fn(),
      updateItem: vi.fn(),
      removeItem: vi.fn(),
      removeItems: vi.fn(),
      setSelection: vi.fn(),
      setSelections: vi.fn(),
      clearSelection: vi.fn(),
      startConnection: vi.fn(),
      completeConnection: vi.fn(),
      removeConnection: vi.fn(),
      updateViewport: vi.fn()
    })

    useCanvasGeneration.mockReturnValue({
      generationLoadingByItem: {},
      generationHistories: {},
      historyLoadingByItem: {},
      loadHistory: vi.fn(),
      generate: vi.fn(),
      applyGeneration: vi.fn()
    })

    const wrapper = mount(CanvasEditor, {
      global: {
        directives: {
          loading: {
            mounted() {},
            updated() {}
          }
        },
        stubs: {
          CanvasConnectionActions: true,
          CanvasGenerationHistoryDrawer: true,
          CanvasImageStudio: true,
          CanvasLinkCreateMenu: true,
          CanvasLinkDragOverlay: true,
          CanvasWorkbenchLayout: {
            name: 'CanvasWorkbenchLayout',
            props: ['zoomHintText'],
            template: '<div class="workbench-stub" :data-zoom-hint-text="zoomHintText"><slot /></div>'
          },
          CanvasTextStudio: true,
          CanvasVideoStudio: true,
          KonvaCanvasStage: true
        }
      }
    })

    expect(wrapper.get('.workbench-stub').attributes('data-zoom-hint-text')).toContain(
      '按住 Shift 左键拖拽框选节点'
    )
    wrapper.unmount()
  })

  it('saves dirty editor state before assistant-triggered reload', async () => {
    const save = vi.fn(async () => ({}))
    const loadDocument = vi.fn(async () => {})
    const setSelection = vi.fn()
    const clearSelection = vi.fn()
    const selectedItem = ref({
      id: 'item-1',
      item_type: 'text',
      title: '文本节点 1',
      position_x: 20,
      position_y: 30,
      width: 320,
      height: 220,
      z_index: 1,
      content: { text: 'hello', promptTokens: [] },
      generation_config: {},
      last_run_status: 'idle',
      last_run_error: null,
      last_output: {},
      has_detail: true,
      is_persisted: true
    })

    useCanvasEditor.mockReturnValue({
      loading: ref(false),
      saving: ref(false),
      document: ref({ id: 'doc-1', title: 'Canvas Doc' }),
      items: ref([selectedItem.value]),
      connections: ref([]),
      selectedItemIds: ref(['item-1']),
      selectedItemId: ref('item-1'),
      selectedItem,
      zoom: ref(1),
      pan: ref({ x: 0, y: 0 }),
      dirty: ref(true),
      loadDocument,
      save,
      createItem: vi.fn(),
      updateItem: vi.fn(),
      removeItem: vi.fn(),
      removeItems: vi.fn(),
      setSelection,
      setSelections: vi.fn(),
      clearSelection,
      startConnection: vi.fn(),
      completeConnection: vi.fn(),
      removeConnection: vi.fn(),
      updateViewport: vi.fn()
    })

    useCanvasGeneration.mockReturnValue({
      generationLoadingByItem: {},
      generationHistories: {},
      historyLoadingByItem: {},
      loadHistory: vi.fn(),
      generate: vi.fn(),
      applyGeneration: vi.fn()
    })

    const wrapper = mount(CanvasEditor, {
      global: {
        directives: {
          loading: {
            mounted() {},
            updated() {}
          }
        },
        stubs: {
          CanvasConnectionActions: true,
          CanvasGenerationHistoryDrawer: true,
          CanvasImageStudio: true,
          CanvasLinkCreateMenu: true,
          CanvasLinkDragOverlay: true,
          CanvasWorkbenchLayout: {
            name: 'CanvasWorkbenchLayout',
            template: '<div class="workbench-stub"><slot /></div>'
          },
          CanvasTextStudio: true,
          CanvasVideoStudio: true,
          KonvaCanvasStage: true
        }
      }
    })

    const assistant = wrapper.findComponent({ name: 'CanvasAssistant' })
    await assistant.props('refreshCanvas')({ documentId: 'doc-1' })

    expect(save).toHaveBeenCalledTimes(1)
    expect(loadDocument).toHaveBeenCalledWith('doc-1')
    expect(setSelection).toHaveBeenCalledWith('item-1')
    expect(clearSelection).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('selects every node hit by the marquee box', async () => {
    const setSelections = vi.fn()
    useCanvasEditor.mockReturnValue({
      loading: ref(false),
      saving: ref(false),
      document: ref({ id: 'doc-1', title: 'Canvas Doc' }),
      items: ref([
        {
          id: 'item-1',
          item_type: 'text',
          title: '文本节点 1',
          position_x: 20,
          position_y: 30,
          width: 100,
          height: 80,
          z_index: 1,
          content: { text: '', promptTokens: [] },
          generation_config: {},
          last_output: {}
        },
        {
          id: 'item-2',
          item_type: 'image',
          title: '图片节点 1',
          position_x: 180,
          position_y: 60,
          width: 120,
          height: 90,
          z_index: 2,
          content: { promptTokens: [] },
          generation_config: {},
          last_output: {}
        }
      ]),
      connections: ref([]),
      selectedItemIds: ref([]),
      selectedItemId: ref(null),
      selectedItem: ref(null),
      zoom: ref(1),
      pan: ref({ x: 0, y: 0 }),
      dirty: ref(false),
      loadDocument: vi.fn(),
      save: vi.fn(),
      createItem: vi.fn(),
      updateItem: vi.fn(),
      removeItem: vi.fn(),
      removeItems: vi.fn(),
      setSelection: vi.fn(),
      setSelections,
      clearSelection: vi.fn(),
      startConnection: vi.fn(),
      completeConnection: vi.fn(),
      removeConnection: vi.fn(),
      updateViewport: vi.fn()
    })

    useCanvasGeneration.mockReturnValue({
      generationLoadingByItem: {},
      generationHistories: {},
      historyLoadingByItem: {},
      loadHistory: vi.fn(),
      generate: vi.fn(),
      applyGeneration: vi.fn()
    })

    const wrapper = mount(CanvasEditor, {
      global: {
        directives: {
          loading: {
            mounted() {},
            updated() {}
          }
        },
        stubs: {
          CanvasConnectionActions: true,
          CanvasGenerationHistoryDrawer: true,
          CanvasImageStudio: true,
          CanvasLinkCreateMenu: true,
          CanvasLinkDragOverlay: true,
          CanvasWorkbenchLayout: {
            name: 'CanvasWorkbenchLayout',
            template: '<div class="workbench-stub"><slot /></div>'
          },
          CanvasTextStudio: true,
          CanvasVideoStudio: true,
          KonvaCanvasStage: {
            name: 'KonvaCanvasStage',
            emits: ['selection-box-end'],
            template:
              '<button class="stage-selection-box" @click="$emit(\'selection-box-end\', { bounds: { left: 0, top: 0, right: 320, bottom: 180 }, appendToSelection: false })"></button>'
          }
        }
      }
    })

    await wrapper.get('.stage-selection-box').trigger('click')

    expect(setSelections).toHaveBeenCalledWith(['item-1', 'item-2'])
    wrapper.unmount()
  })

  it('confirms before deleting all selected nodes with one batch request', async () => {
    const removeItems = vi.fn(async () => {})
    ElMessageBox.confirm.mockResolvedValue('confirm')

    useCanvasEditor.mockReturnValue({
      loading: ref(false),
      saving: ref(false),
      document: ref({ id: 'doc-1', title: 'Canvas Doc' }),
      items: ref([
        { id: 'item-1', item_type: 'text', title: '文本节点 1', position_x: 0, position_y: 0, width: 100, height: 80, z_index: 1, content: {}, generation_config: {}, last_output: {} },
        { id: 'item-2', item_type: 'image', title: '图片节点 1', position_x: 120, position_y: 0, width: 100, height: 80, z_index: 2, content: {}, generation_config: {}, last_output: {} }
      ]),
      connections: ref([]),
      selectedItemIds: ref(['item-1', 'item-2']),
      selectedItemId: ref(null),
      selectedItem: ref(null),
      zoom: ref(1),
      pan: ref({ x: 0, y: 0 }),
      dirty: ref(false),
      loadDocument: vi.fn(),
      save: vi.fn(),
      createItem: vi.fn(),
      updateItem: vi.fn(),
      removeItem: vi.fn(),
      removeItems,
      setSelection: vi.fn(),
      setSelections: vi.fn(),
      clearSelection: vi.fn(),
      startConnection: vi.fn(),
      completeConnection: vi.fn(),
      removeConnection: vi.fn(),
      updateViewport: vi.fn()
    })

    useCanvasGeneration.mockReturnValue({
      generationLoadingByItem: {},
      generationHistories: {},
      historyLoadingByItem: {},
      loadHistory: vi.fn(),
      generate: vi.fn(),
      applyGeneration: vi.fn()
    })

    const wrapper = mount(CanvasEditor, {
      global: {
        directives: {
          loading: {
            mounted() {},
            updated() {}
          }
        },
        stubs: {
          CanvasConnectionActions: true,
          CanvasGenerationHistoryDrawer: true,
          CanvasImageStudio: true,
          CanvasLinkCreateMenu: true,
          CanvasLinkDragOverlay: true,
          CanvasWorkbenchLayout: {
            name: 'CanvasWorkbenchLayout',
            template: '<div class="workbench-stub"><slot /></div>'
          },
          CanvasTextStudio: true,
          CanvasVideoStudio: true,
          KonvaCanvasStage: true
        }
      }
    })

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Delete' }))
    await Promise.resolve()
    await Promise.resolve()

    expect(ElMessageBox.confirm).toHaveBeenCalledTimes(1)
    expect(ElMessageBox.confirm.mock.calls[0][0]).toContain('2')
    expect(removeItems).toHaveBeenCalledWith(['item-1', 'item-2'])
    wrapper.unmount()
  })

  it('confirms before deleting a single node from the studio panel', async () => {
    const removeItems = vi.fn(async () => {})
    ElMessageBox.confirm.mockResolvedValue('confirm')
    const selectedItem = ref({
      id: 'item-1',
      item_type: 'text',
      title: '文本节点 1',
      position_x: 20,
      position_y: 30,
      width: 320,
      height: 220,
      z_index: 1,
      content: { text: 'hello', promptTokens: [] },
      generation_config: {},
      last_run_status: 'idle',
      last_run_error: null,
      last_output: {},
      has_detail: true,
      is_persisted: true
    })

    useCanvasEditor.mockReturnValue({
      loading: ref(false),
      saving: ref(false),
      document: ref({ id: 'doc-1', title: 'Canvas Doc' }),
      items: ref([selectedItem.value]),
      connections: ref([]),
      selectedItemIds: ref(['item-1']),
      selectedItemId: ref('item-1'),
      selectedItem,
      zoom: ref(1),
      pan: ref({ x: 0, y: 0 }),
      dirty: ref(false),
      loadDocument: vi.fn(),
      save: vi.fn(),
      createItem: vi.fn(),
      updateItem: vi.fn(),
      removeItem: vi.fn(),
      removeItems,
      setSelection: vi.fn(),
      setSelections: vi.fn(),
      clearSelection: vi.fn(),
      startConnection: vi.fn(),
      completeConnection: vi.fn(),
      removeConnection: vi.fn(),
      updateViewport: vi.fn()
    })

    useCanvasGeneration.mockReturnValue({
      generationLoadingByItem: {},
      generationHistories: {},
      historyLoadingByItem: {},
      loadHistory: vi.fn(),
      generate: vi.fn(),
      applyGeneration: vi.fn()
    })

    const wrapper = mount(CanvasEditor, {
      global: {
        directives: {
          loading: {
            mounted() {},
            updated() {}
          }
        },
        stubs: {
          CanvasConnectionActions: true,
          CanvasGenerationHistoryDrawer: true,
          CanvasImageStudio: true,
          CanvasLinkCreateMenu: true,
          CanvasLinkDragOverlay: true,
          CanvasWorkbenchLayout: {
            name: 'CanvasWorkbenchLayout',
            template: '<div class="workbench-stub"><slot /></div>'
          },
          CanvasTextStudio: {
            name: 'CanvasTextStudio',
            emits: ['delete'],
            template: '<button class="single-delete" @click="$emit(\'delete\')"></button>'
          },
          CanvasVideoStudio: true,
          KonvaCanvasStage: true
        }
      }
    })

    await wrapper.get('.single-delete').trigger('click')
    await Promise.resolve()

    expect(ElMessageBox.confirm).toHaveBeenCalledTimes(1)
    expect(ElMessageBox.confirm.mock.calls[0][0]).toContain('该节点')
    expect(removeItems).toHaveBeenCalledWith(['item-1'])
    wrapper.unmount()
  })

  it('creates image nodes with default api key and model from the loaded catalog', async () => {
    const createItem = vi.fn(async () => ({
      id: 'item-image-1',
      item_type: 'image'
    }))

    useCanvasEditor.mockReturnValue({
      loading: ref(false),
      saving: ref(false),
      document: ref({ id: 'doc-1', title: 'Canvas Doc' }),
      items: ref([]),
      connections: ref([]),
      selectedItemIds: ref([]),
      selectedItemId: ref(null),
      selectedItem: ref(null),
      zoom: ref(1),
      pan: ref({ x: 0, y: 0 }),
      dirty: ref(false),
      loadDocument: vi.fn(),
      save: vi.fn(),
      createItem,
      updateItem: vi.fn(),
      removeItem: vi.fn(),
      removeItems: vi.fn(),
      setSelection: vi.fn(),
      setSelections: vi.fn(),
      clearSelection: vi.fn(),
      startConnection: vi.fn(),
      completeConnection: vi.fn(),
      removeConnection: vi.fn(),
      updateViewport: vi.fn()
    })

    const { apiKeysService } = await import('@/services/apiKeys')
    const { canvasService } = await import('@/services/canvas')
    apiKeysService.getAPIKeys.mockResolvedValue({
      api_keys: [{ id: 'key-1', name: '主 Key', provider: 'siliconflow' }]
    })
    canvasService.getModelCatalog.mockResolvedValue({
      connections: { 'key-1': { models: [
        { id: 'image-model-1', type: 'image', enabled: true, available: true },
        { id: 'image-model-2', type: 'image', enabled: true, available: true }
      ] } }
    })

    useCanvasGeneration.mockReturnValue({
      generationLoadingByItem: {},
      generationHistories: {},
      historyLoadingByItem: {},
      loadHistory: vi.fn(),
      generate: vi.fn(),
      applyGeneration: vi.fn()
    })

    const wrapper = mount(CanvasEditor, {
      global: {
        directives: {
          loading: {
            mounted() {},
            updated() {}
          }
        },
        stubs: {
          CanvasConnectionActions: true,
          CanvasGenerationHistoryDrawer: true,
          CanvasImageStudio: true,
          CanvasLinkCreateMenu: true,
          CanvasLinkDragOverlay: true,
          CanvasWorkbenchLayout: {
            name: 'CanvasWorkbenchLayout',
            emits: ['create-item'],
            template:
              '<div class="workbench-stub"><button class="create-image-node" @click="$emit(\'create-item\', \'image\')"></button><slot /></div>'
          },
          CanvasTextStudio: true,
          CanvasVideoStudio: true,
          KonvaCanvasStage: true
        }
      }
    })

    await nextTick()
    await Promise.resolve()
    await wrapper.get('.create-image-node').trigger('click')
    await Promise.resolve()

    expect(createItem).toHaveBeenCalledWith('image', {
      generation_config: {
        api_key_id: 'key-1',
        model: 'image-model-1'
      }
    })

    wrapper.unmount()
  })

  it('uses the original item id to refresh history after generation succeeds even if selection is cleared', async () => {
    const loadHistory = vi.fn(async () => [])
    const generate = vi.fn(async () => {
      selectedItem.value = null
      return { message: '生成任务已提交' }
    })
    const save = vi.fn(async () => ({}))
    const selectedItem = ref({
      id: 'item-image-1',
      item_type: 'image',
      title: '图片节点 1',
      position_x: 20,
      position_y: 30,
      width: 320,
      height: 220,
      z_index: 1,
      content: { prompt: 'hello', promptTokens: [] },
      generation_config: { api_key_id: 'key-1', model: 'image-model-1' },
      last_run_status: 'idle',
      last_run_error: null,
      last_output: {},
      has_detail: true,
      is_persisted: true
    })

    useCanvasEditor.mockReturnValue({
      loading: ref(false),
      saving: ref(false),
      document: ref({ id: 'doc-1', title: 'Canvas Doc' }),
      items: ref([selectedItem.value]),
      connections: ref([]),
      selectedItemIds: ref(['item-image-1']),
      selectedItemId: ref('item-image-1'),
      selectedItem,
      zoom: ref(1),
      pan: ref({ x: 0, y: 0 }),
      dirty: ref(true),
      loadDocument: vi.fn(),
      save,
      createItem: vi.fn(),
      updateItem: vi.fn(),
      removeItem: vi.fn(),
      removeItems: vi.fn(),
      setSelection: vi.fn(),
      setSelections: vi.fn(),
      clearSelection: vi.fn(),
      startConnection: vi.fn(),
      completeConnection: vi.fn(),
      removeConnection: vi.fn(),
      updateViewport: vi.fn()
    })

    useCanvasGeneration.mockReturnValue({
      generationLoadingByItem: {},
      generationHistories: {},
      historyLoadingByItem: {},
      loadHistory,
      generate,
      applyGeneration: vi.fn()
    })

    const successSpy = vi.spyOn(ElMessage, 'success').mockImplementation(() => {})
    const errorSpy = vi.spyOn(ElMessage, 'error').mockImplementation(() => {})

    const wrapper = mount(CanvasEditor, {
      global: {
        directives: {
          loading: {
            mounted() {},
            updated() {}
          }
        },
        stubs: {
          CanvasConnectionActions: true,
          CanvasGenerationHistoryDrawer: { name: 'CanvasGenerationHistoryDrawer', emits: ['select'], template: '<div />' },
          CanvasImageStudio: {
            name: 'CanvasImageStudio',
            emits: ['generate', 'history'],
            template: '<button class="generate-image" @click="$emit(\'generate\')"></button>'
          },
          CanvasLinkCreateMenu: true,
          CanvasLinkDragOverlay: true,
          CanvasWorkbenchLayout: {
            name: 'CanvasWorkbenchLayout',
            template: '<div class="workbench-stub"><slot /></div>'
          },
          CanvasTextStudio: true,
          CanvasVideoStudio: true,
          KonvaCanvasStage: true
        }
      }
    })

    await flushPromises()
    await wrapper.get('.generate-image').trigger('click')
    await Promise.resolve()
    await Promise.resolve()

    expect(save).toHaveBeenCalledTimes(1)
    expect(generate).toHaveBeenCalledTimes(1)
    expect(loadHistory).toHaveBeenCalledWith('item-image-1')
    expect(successSpy).toHaveBeenCalled()
    expect(errorSpy).not.toHaveBeenCalled()
    // Restoring a stored asset must remain possible after its model was hidden.
    const originalItem = useCanvasEditor.mock.results.at(-1).value.items.value[0]
    originalItem.generation_config.model = 'hidden-old-model'
    selectedItem.value = originalItem
    await nextTick()
    wrapper.findComponent({ name: 'CanvasImageStudio' }).vm.$emit('history')
    await flushPromises()
    wrapper.findComponent({ name: 'CanvasGenerationHistoryDrawer' }).vm.$emit('select', { id: 'old-generation' })
    await flushPromises()
    expect(useCanvasGeneration.mock.results.at(-1).value.applyGeneration).toHaveBeenCalledWith(originalItem, 'old-generation')

    successSpy.mockRestore()
    errorSpy.mockRestore()
    wrapper.unmount()
  })
})
