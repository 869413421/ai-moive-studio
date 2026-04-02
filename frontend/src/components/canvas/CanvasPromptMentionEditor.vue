<template>
  <div class="canvas-prompt-mention-editor">
    <div ref="promptPanelShellRef" class="prompt-panel-shell">
      <div
        ref="editableRef"
        class="prompt-editor"
        :class="{ 'is-disabled': disabled }"
        contenteditable="true"
        :data-placeholder="promptPlaceholder"
        @focus="handleEditorFocus"
        @compositionstart="handleEditorCompositionStart"
        @compositionend="handleEditorCompositionEnd"
        @input="handleEditorInput"
        @keydown="handleEditorKeydown"
        @keyup="handleEditorKeyup"
        @click="handleEditorClick"
        @blur="handleEditorBlur"
        @paste="handleEditorPaste"
      ></div>

      <div
        v-if="showReferencePicker"
        class="reference-picker"
        :class="referencePickerPlacementClass"
        :style="referencePickerStyle"
      >
        <div class="reference-picker-header">
          <div class="reference-picker-header-main">
            <span class="reference-picker-title">{{ referencePickerTitle }}</span>
            <span class="reference-picker-count">{{ flattenedReferenceItems.length }}</span>
          </div>
          <span class="reference-picker-query">@{{ referenceQuery }}</span>
        </div>
        <div class="reference-picker-subtitle">{{ referencePickerSubtitle }}</div>
        <div class="reference-picker-search-hint">{{ referencePickerSearchHint }}</div>
        <div v-if="flattenedReferenceItems.length" class="reference-list">
          <div v-for="group in groupedReferenceItems" :key="group.key" class="reference-group">
            <div class="reference-group-title">{{ group.title }}</div>
            <button
              v-for="reference in group.items"
              :key="reference.id"
              type="button"
              class="reference-item"
              :class="{ 'is-active': reference.flatIndex === activeReferenceIndex }"
              @mousedown.prevent="insertReference(reference)"
            >
              <span v-if="reference.item_type === 'image' && reference.previewUrl" class="reference-item-thumb-wrap">
                <img class="reference-item-thumb" :src="reference.previewUrl" :alt="reference.title || reference.id" />
              </span>
              <span v-else class="reference-item-type">{{ reference.item_type === 'image' ? 'IMG' : 'TXT' }}</span>
              <span class="reference-item-body">
                <span class="reference-item-title-row">
                  <span class="reference-item-title">{{ reference.title || reference.id }}</span>
                  <span class="reference-item-kind">{{ reference.item_type === 'image' ? '图片' : '文本' }}</span>
                </span>
                <span class="reference-item-meta">{{ referenceSummary(reference) }}</span>
              </span>
              <span class="reference-item-action">{{ reference.flatIndex === activeReferenceIndex ? 'Enter' : '+' }}</span>
            </button>
          </div>
        </div>
        <div v-else class="reference-empty">
          <div class="reference-empty-title">暂无结果</div>
          <div class="reference-empty-hint">{{ referencePickerEmptyHint }}</div>
        </div>
      </div>
    </div>

    <div v-if="helperText" class="prompt-hint-row">
      <span>{{ helperText }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  tokens: { type: Array, default: () => [] },
  availableReferenceItems: { type: Array, default: () => [] },
  globalReferenceItems: { type: Array, default: () => [] },
  promptPlaceholder: { type: String, default: '' },
  referencePickerTitle: { type: String, default: '引用节点' },
  helperText: { type: String, default: '' },
  disabled: { type: Boolean, default: false }
})

const emit = defineEmits(['focus-item', 'update:tokens'])

const editableRef = ref(null)
const promptPanelShellRef = ref(null)
const referenceQuery = ref('')
const showReferencePicker = ref(false)
const mentionRange = ref(null)
const activeReferenceIndex = ref(0)
const isSyncingEditor = ref(false)
const isComposing = ref(false)
const localTokens = ref([])
const localTokenSignature = ref('[]')
const referencePickerPlacement = ref('above')
const referencePickerMaxHeight = ref(280)
const mentionQueryFrame = ref(0)

const filteredReferenceItems = computed(() => {
  const keyword = referenceQuery.value.toLowerCase()
  return props.availableReferenceItems.filter((item) => {
    if (!keyword) {
      return true
    }

    const title = String(item.title || '').toLowerCase()
    const summary = referenceSummary(item).toLowerCase()
    return title.includes(keyword) || summary.includes(keyword)
  })
})

const groupedReferenceItems = computed(() => {
  const keyword = referenceQuery.value.toLowerCase()
  const upstreamItems = filteredReferenceItems.value
  if (!keyword) {
    return upstreamItems.length
      ? [{ key: 'upstream-default', title: '上游可引用节点', items: upstreamItems.map((item, index) => ({ ...item, flatIndex: index })) }]
      : []
  }

  const upstreamIds = new Set(upstreamItems.map((item) => String(item.id || '')))
  const globalItems = props.globalReferenceItems.filter((item) => {
    const itemId = String(item?.id || '')
    if (!itemId || upstreamIds.has(itemId)) {
      return false
    }

    const title = String(item.title || '').toLowerCase()
    const summary = referenceSummary(item).toLowerCase()
    return title.includes(keyword) || summary.includes(keyword)
  })

  const groups = []
  let flatIndex = 0
  if (upstreamItems.length) {
    groups.push({
      key: 'upstream-search',
      title: '上游匹配',
      items: upstreamItems.map((item) => ({ ...item, flatIndex: flatIndex++ }))
    })
  }
  if (globalItems.length) {
    groups.push({
      key: 'global-search',
      title: '全局结果',
      items: globalItems.map((item) => ({ ...item, flatIndex: flatIndex++ }))
    })
  }
  return groups
})

const flattenedReferenceItems = computed(() => groupedReferenceItems.value.flatMap((group) => group.items))
const referencePickerPlacementClass = computed(() => (
  referencePickerPlacement.value === 'below' ? 'is-below' : 'is-above'
))
const referencePickerStyle = computed(() => ({
  '--picker-max-height': `${referencePickerMaxHeight.value}px`
}))
const referencePickerSubtitle = computed(() => (
  referenceQuery.value ? '优先显示上游匹配，并补充全画布搜索结果' : '默认只显示当前节点上游可追溯的文本和图片节点'
))
const referencePickerSearchHint = computed(() => (
  referenceQuery.value ? '正在搜索全画布节点' : '继续输入关键词，可搜索全画布节点'
))
const referencePickerEmptyHint = computed(() => (
  referenceQuery.value ? '没有命中结果，试试别的关键词' : '继续输入关键词，或先在画布中建立上游连线'
))

const serializeTokens = (tokens = []) => JSON.stringify(tokens)

const escapeHtml = (value = '') =>
  String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')

const renderTextToken = (token) => escapeHtml(token.text || '').replace(/\n/g, '<br>')

const renderMentionToken = (token) => {
  const title = escapeHtml(token.nodeTitleSnapshot || token.nodeId || '')
  const preview = escapeHtml(String(token.nodePreviewUrlSnapshot || '').trim())
  const previewHtml = token.nodeType === 'image' && preview
    ? `<img class="mention-token-thumb" src="${preview}" alt="${title}" />`
    : '<span class="mention-token-kind">T</span>'

  return `<span class="mention-token" contenteditable="false" data-token-type="mention" data-node-id="${escapeHtml(token.nodeId || '')}" data-node-type="${escapeHtml(token.nodeType || '')}" data-node-title="${title}" data-node-preview="${preview}">${previewHtml}<span class="mention-token-label">@${title}</span><span class="mention-token-remove" data-action="remove">×</span></span>`
}

const renderEditor = async (tokens = localTokens.value) => {
  if (!editableRef.value) {
    return
  }

  const html = tokens.map((token) => (token.type === 'mention' ? renderMentionToken(token) : renderTextToken(token))).join('')
  isSyncingEditor.value = true
  editableRef.value.innerHTML = html || ''
  await nextTick()
  isSyncingEditor.value = false
}

const normalizeTextTokenBuffer = (tokens, text) => {
  if (!text) {
    return
  }
  const previous = tokens[tokens.length - 1]
  if (previous?.type === 'text') {
    previous.text += text
    return
  }
  tokens.push({ type: 'text', text })
}

const parseTokensFromNode = (node, tokens) => {
  if (!node) {
    return
  }

  if (node.nodeType === Node.TEXT_NODE) {
    normalizeTextTokenBuffer(tokens, node.textContent || '')
    return
  }

  if (node.nodeType !== Node.ELEMENT_NODE) {
    return
  }

  const element = node
  if (element.dataset?.tokenType === 'mention') {
    tokens.push({
      type: 'mention',
      nodeId: element.dataset.nodeId || '',
      nodeType: element.dataset.nodeType || '',
      nodeTitleSnapshot: element.dataset.nodeTitle || '',
      nodePreviewUrlSnapshot: element.dataset.nodePreview || ''
    })
    return
  }

  if (element.tagName === 'BR') {
    normalizeTextTokenBuffer(tokens, '\n')
    return
  }

  Array.from(element.childNodes || []).forEach((child) => parseTokensFromNode(child, tokens))
  if (['DIV', 'P'].includes(element.tagName) && element.nextSibling) {
    normalizeTextTokenBuffer(tokens, '\n')
  }
}

const syncLocalTokensFromEditor = () => {
  if (!editableRef.value || isSyncingEditor.value) {
    return
  }

  const nextTokens = []
  Array.from(editableRef.value.childNodes || []).forEach((node) => parseTokensFromNode(node, nextTokens))
  const nextSignature = serializeTokens(nextTokens)
  if (nextSignature === localTokenSignature.value) {
    return
  }

  localTokens.value = nextTokens
  localTokenSignature.value = nextSignature
  if (!isComposing.value) {
    emit('update:tokens', nextTokens)
  }
}

const flushTokens = () => {
  if (!editableRef.value || isSyncingEditor.value) {
    return Array.isArray(localTokens.value) ? localTokens.value : []
  }

  const nextTokens = []
  Array.from(editableRef.value.childNodes || []).forEach((node) => parseTokensFromNode(node, nextTokens))
  const nextSignature = serializeTokens(nextTokens)
  localTokens.value = nextTokens
  localTokenSignature.value = nextSignature
  emit('update:tokens', nextTokens)
  return nextTokens
}

const selectionInsideEditor = (node) => editableRef.value && node && editableRef.value.contains(node)

const closeReferencePicker = () => {
  showReferencePicker.value = false
  referenceQuery.value = ''
  mentionRange.value = null
  activeReferenceIndex.value = 0
}

const cancelMentionQueryFrame = () => {
  if (mentionQueryFrame.value && typeof window !== 'undefined') {
    window.cancelAnimationFrame(mentionQueryFrame.value)
  }
  mentionQueryFrame.value = 0
}

const updateReferencePickerLayout = () => {
  if (!promptPanelShellRef.value || !showReferencePicker.value) {
    return
  }

  const rect = promptPanelShellRef.value.getBoundingClientRect()
  const viewportHeight = typeof window !== 'undefined' ? window.innerHeight : 800
  const viewportPadding = 16
  const preferredHeight = 280
  const pickerGap = 10
  const spaceAbove = Math.max(0, rect.top - viewportPadding - pickerGap)
  const spaceBelow = Math.max(0, viewportHeight - rect.bottom - viewportPadding - pickerGap)
  const shouldOpenBelow = spaceBelow >= spaceAbove
  referencePickerPlacement.value = shouldOpenBelow ? 'below' : 'above'
  referencePickerMaxHeight.value = Math.max(0, Math.min(preferredHeight, shouldOpenBelow ? spaceBelow : spaceAbove))
}

const walkToLastTextNode = (node) => {
  let cursor = node
  while (cursor) {
    if (cursor.nodeType === Node.TEXT_NODE) {
      return cursor
    }
    const children = cursor.childNodes || []
    cursor = children.length ? children[children.length - 1] : null
  }
  return null
}

const resolveCaretTextContext = (container, offset) => {
  if (!editableRef.value || !container) {
    return null
  }
  if (container.nodeType === Node.TEXT_NODE) {
    return {
      node: container,
      offset: Math.min(offset, String(container.textContent || '').length)
    }
  }
  if (container.nodeType !== Node.ELEMENT_NODE) {
    return null
  }
  const children = Array.from(container.childNodes || [])
  const previousChild = offset > 0 ? children[offset - 1] : null
  const previousTextNode = walkToLastTextNode(previousChild)
  if (!previousTextNode) {
    return null
  }
  return {
    node: previousTextNode,
    offset: String(previousTextNode.textContent || '').length
  }
}

const updateMentionQuery = () => {
  const selection = window.getSelection()
  if (!selection || selection.rangeCount === 0) {
    closeReferencePicker()
    return
  }

  const range = selection.getRangeAt(0)
  if (!range.collapsed || !selectionInsideEditor(range.endContainer)) {
    closeReferencePicker()
    return
  }

  const caretContext = resolveCaretTextContext(range.endContainer, range.endOffset)
  if (!caretContext?.node) {
    closeReferencePicker()
    return
  }

  const textBeforeCaret = String(caretContext.node.textContent || '').slice(0, caretContext.offset)
  const match = textBeforeCaret.match(/(?:^|\s)@([^\s@]*)$/)
  if (!match) {
    closeReferencePicker()
    return
  }

  const query = match[1] || ''
  const mentionText = `@${query}`
  const startOffset = textBeforeCaret.lastIndexOf(mentionText)
  if (startOffset < 0) {
    closeReferencePicker()
    return
  }

  const nextRange = document.createRange()
  nextRange.setStart(caretContext.node, startOffset)
  nextRange.setEnd(caretContext.node, caretContext.offset)
  mentionRange.value = nextRange
  referenceQuery.value = query
  showReferencePicker.value = true
  updateReferencePickerLayout()
  if (activeReferenceIndex.value >= flattenedReferenceItems.value.length) {
    activeReferenceIndex.value = 0
  }
}

const scheduleMentionQueryUpdate = () => {
  if (typeof window === 'undefined') {
    updateMentionQuery()
    return
  }

  cancelMentionQueryFrame()
  mentionQueryFrame.value = window.requestAnimationFrame(() => {
    mentionQueryFrame.value = 0
    updateMentionQuery()
  })
}

const placeCaretAfterNode = (node) => {
  const selection = window.getSelection()
  if (!selection || !node) {
    return
  }
  const range = document.createRange()
  range.setStartAfter(node)
  range.collapse(true)
  selection.removeAllRanges()
  selection.addRange(range)
}

const insertReference = (reference) => {
  if (!editableRef.value || props.disabled) {
    return
  }

  editableRef.value.focus()
  const selection = window.getSelection()
  const range = mentionRange.value || (selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null)
  if (!range) {
    return
  }

  range.deleteContents()
  const token = document.createElement('span')
  token.className = 'mention-token'
  token.contentEditable = 'false'
  token.dataset.tokenType = 'mention'
  token.dataset.nodeId = reference.id
  token.dataset.nodeType = reference.item_type
  token.dataset.nodeTitle = reference.title || reference.id
  token.dataset.nodePreview = reference.previewUrl || ''
  token.innerHTML = reference.item_type === 'image' && reference.previewUrl
    ? `<img class="mention-token-thumb" src="${escapeHtml(reference.previewUrl)}" alt="${escapeHtml(reference.title || reference.id)}" /><span class="mention-token-label">@${escapeHtml(reference.title || reference.id)}</span><span class="mention-token-remove" data-action="remove">×</span>`
    : `<span class="mention-token-kind">T</span><span class="mention-token-label">@${escapeHtml(reference.title || reference.id)}</span><span class="mention-token-remove" data-action="remove">×</span>`

  const trailingSpace = document.createTextNode(' ')
  range.insertNode(trailingSpace)
  range.insertNode(token)
  placeCaretAfterNode(trailingSpace)
  closeReferencePicker()
  syncLocalTokensFromEditor()
}

const removeMentionToken = (tokenElement) => {
  if (!tokenElement) {
    return
  }
  tokenElement.remove()
  syncLocalTokensFromEditor()
  updateMentionQuery()
}

const handleEditorCompositionStart = () => {
  isComposing.value = true
}

const handleEditorCompositionEnd = () => {
  isComposing.value = false
  syncLocalTokensFromEditor()
  scheduleMentionQueryUpdate()
}

const handleEditorInput = () => {
  if (props.disabled) {
    return
  }
  syncLocalTokensFromEditor()
  scheduleMentionQueryUpdate()
}

const handleEditorKeydown = (event) => {
  if (props.disabled) {
    event.preventDefault()
    return
  }

  if (showReferencePicker.value && event.key === 'Escape') {
    event.preventDefault()
    closeReferencePicker()
    return
  }

  if (!showReferencePicker.value || flattenedReferenceItems.value.length === 0) {
    return
  }

  if (event.key === 'ArrowDown') {
    event.preventDefault()
    activeReferenceIndex.value = (activeReferenceIndex.value + 1) % flattenedReferenceItems.value.length
    return
  }

  if (event.key === 'ArrowUp') {
    event.preventDefault()
    activeReferenceIndex.value = (activeReferenceIndex.value - 1 + flattenedReferenceItems.value.length) % flattenedReferenceItems.value.length
    return
  }

  if (event.key === 'Enter' || event.key === 'Tab') {
    event.preventDefault()
    insertReference(flattenedReferenceItems.value[activeReferenceIndex.value] || flattenedReferenceItems.value[0])
  }
}

const handleEditorClick = (event) => {
  const removeTarget = event.target.closest('[data-action="remove"]')
  if (removeTarget) {
    removeMentionToken(removeTarget.closest('.mention-token'))
    return
  }

  const tokenElement = event.target.closest('.mention-token')
  if (tokenElement?.dataset?.nodeId) {
    emit('focus-item', tokenElement.dataset.nodeId)
  }
  scheduleMentionQueryUpdate()
}

const handleEditorBlur = () => {
  syncLocalTokensFromEditor()
  cancelMentionQueryFrame()
  setTimeout(() => {
    const activeElement = typeof document !== 'undefined' ? document.activeElement : null
    if (activeElement && activeElement.closest('.reference-picker')) {
      return
    }
    closeReferencePicker()
  }, 0)
}

const handleEditorPaste = (event) => {
  event.preventDefault()
  const pastedText = event.clipboardData?.getData('text/plain') || ''
  document.execCommand('insertText', false, pastedText)
  scheduleMentionQueryUpdate()
}

const handleEditorFocus = () => {
  scheduleMentionQueryUpdate()
}

const handleEditorKeyup = (event) => {
  if (['ArrowDown', 'ArrowUp', 'Enter', 'Tab', 'Escape'].includes(event.key)) {
    return
  }
  scheduleMentionQueryUpdate()
}

const handleDocumentSelectionChange = () => {
  const selection = typeof window !== 'undefined' ? window.getSelection() : null
  if (!selection || selection.rangeCount === 0) {
    return
  }

  if (!selectionInsideEditor(selection.anchorNode)) {
    return
  }

  scheduleMentionQueryUpdate()
}

const referenceSummary = (item) => {
  if (item.item_type === 'text') {
    return String(item.previewText || item.content?.text || '').slice(0, 36) || '文本'
  }
  return '图片'
}

watch(
  () => props.tokens,
  (tokens) => {
    if (isComposing.value) {
      return
    }
    const nextTokens = Array.isArray(tokens) ? tokens : []
    const nextSignature = serializeTokens(nextTokens)
    if (nextSignature === localTokenSignature.value) {
      return
    }
    localTokens.value = nextTokens
    localTokenSignature.value = nextSignature
    renderEditor(nextTokens)
  },
  { deep: true, immediate: true }
)

watch(flattenedReferenceItems, (items) => {
  if (!items.length) {
    activeReferenceIndex.value = 0
    return
  }
  updateReferencePickerLayout()
  if (activeReferenceIndex.value >= items.length) {
    activeReferenceIndex.value = 0
  }
})

onMounted(async () => {
  await nextTick()
  await renderEditor(localTokens.value)
  if (typeof window !== 'undefined') {
    window.addEventListener('resize', updateReferencePickerLayout)
    document.addEventListener('selectionchange', handleDocumentSelectionChange)
  }
})

onBeforeUnmount(() => {
  cancelMentionQueryFrame()
  if (typeof window !== 'undefined') {
    window.removeEventListener('resize', updateReferencePickerLayout)
    document.removeEventListener('selectionchange', handleDocumentSelectionChange)
  }
})

defineExpose({
  flushTokens
})
</script>

<style scoped>
.canvas-prompt-mention-editor {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.prompt-panel-shell {
  position: relative;
}

.prompt-editor {
  min-height: 84px;
  max-height: 160px;
  overflow-y: auto;
  padding: 14px 16px;
  border-radius: 18px;
  border: 1px solid rgba(34, 57, 98, 0.1);
  background: #f8fafc;
  color: #1f2a44;
  font-size: 14px;
  line-height: 1.7;
  outline: none;
  white-space: pre-wrap;
  word-break: break-word;
}

.prompt-editor:focus {
  box-shadow: 0 0 0 3px rgba(75, 120, 255, 0.12);
}

.prompt-editor.is-disabled {
  opacity: 0.55;
  pointer-events: none;
}

.prompt-editor:empty::before {
  content: attr(data-placeholder);
  color: #98a2b3;
}

:deep(.mention-token) {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 0 2px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(75, 120, 255, 0.1);
  color: #1f2a44;
}

:deep(.mention-token-thumb) {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  object-fit: cover;
}

:deep(.mention-token-kind) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: rgba(75, 120, 255, 0.14);
  font-size: 11px;
}

.reference-picker {
  position: absolute;
  left: 0;
  right: 0;
  max-height: var(--picker-max-height, 280px);
  padding: 10px;
  border-radius: 16px;
  border: 1px solid rgba(34, 57, 98, 0.1);
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 18px 32px rgba(34, 57, 98, 0.12);
  overflow: hidden;
  z-index: 30;
}

.reference-picker.is-above { bottom: calc(100% + 10px); }
.reference-picker.is-below { top: calc(100% + 10px); }

.reference-picker-header,
.reference-picker-header-main,
.reference-item-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.reference-picker-header { justify-content: space-between; margin-bottom: 8px; }

.reference-picker-title,
.reference-item-title {
  color: #1f2a44;
  font-size: 13px;
  font-weight: 600;
}

.reference-picker-count,
.reference-item-action {
  min-width: 20px;
  padding: 0 6px;
  border-radius: 999px;
  background: rgba(75, 120, 255, 0.12);
  color: #355ce0;
  font-size: 11px;
  text-align: center;
}

.reference-picker-query,
.reference-picker-subtitle,
.reference-picker-search-hint,
.reference-group-title,
.reference-item-meta,
.reference-item-kind,
.reference-empty,
.prompt-hint-row {
  color: #667085;
  font-size: 12px;
}

.reference-picker-search-hint { margin-bottom: 10px; }

.reference-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: calc(var(--picker-max-height, 280px) - 28px);
  overflow-y: auto;
}

.reference-group { display: flex; flex-direction: column; gap: 6px; }

.reference-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 12px;
  border: 1px solid rgba(34, 57, 98, 0.08);
  background: #f8fafc;
  color: #1f2a44;
  text-align: left;
}

.reference-item.is-active {
  background: rgba(75, 120, 255, 0.12);
  border-color: rgba(75, 120, 255, 0.28);
}

.reference-item-thumb-wrap,
.reference-item-type {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  flex-shrink: 0;
}

.reference-item-thumb {
  width: 100%;
  height: 100%;
  border-radius: 8px;
  object-fit: cover;
}

.reference-item-type {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: rgba(75, 120, 255, 0.1);
}

.reference-item-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}
</style>
