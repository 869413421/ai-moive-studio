<template>
  <div
    v-if="item && style"
    ref="rootRef"
    class="canvas-text-studio-context"
    :style="style"
    @mousedown.stop
    @click.stop
    @wheel.stop
    @pointerdown.capture="handleRootPointerDown"
    @focusin="handleRootFocusIn"
  >
    <div class="floating-header" @mousedown.stop="handleHeaderPointerDown">
      <div class="text-label">
        <el-icon class="icon"><Document /></el-icon>
        <span>文本节点</span>
      </div>
      <input
        :value="draft.title"
        class="header-title-input"
        placeholder="文本节点标题"
        :disabled="generating"
        @input="$emit('update:title', $event.target.value)"
      />
    </div>

    <div class="node-handle handle-left" @mousedown.prevent="$emit('handle-drag', $event, 'left')">
      <div class="plus-icon"><el-icon><Plus /></el-icon></div>
    </div>
    <div class="node-handle handle-right" @mousedown.prevent="$emit('handle-drag', $event, 'right')">
      <div class="plus-icon"><el-icon><Plus /></el-icon></div>
    </div>

    <div class="editor-glass-card" @mousedown.stop="handleEditorCardPointerDown">
      <div class="drag-strip drag-strip--top" @mousedown.stop="handleCardDragZonePointerDown"></div>
      <div class="drag-strip drag-strip--right" @mousedown.stop="handleCardDragZonePointerDown"></div>
      <div class="drag-strip drag-strip--bottom" @mousedown.stop="handleCardDragZonePointerDown"></div>
      <div class="drag-strip drag-strip--left" @mousedown.stop="handleCardDragZonePointerDown"></div>
      <div
        ref="editableRef"
        class="rich-textarea"
        :class="{ 'is-empty': !draft.text }"
        :contenteditable="!generating"
        data-placeholder="输入正文内容..."
        @input="handleEditorInput"
        @blur="handleEditorBlur"
      ></div>
    </div>

    <div class="studio-docked-panel">
      <CanvasPromptMentionEditor
        ref="promptEditorRef"
        :tokens="draft.promptTokens"
        :available-reference-items="availableReferenceItems"
        :global-reference-items="globalReferenceItems"
        prompt-placeholder="输入 prompt，可用 @ 引用节点"
        reference-picker-title="引用节点"
        :disabled="generating"
        @focus-item="$emit('focus-item', $event)"
        @update:tokens="$emit('update:tokens', $event)"
      />

      <div class="panel-toolbar">
        <div class="toolbar-left">
          <el-select
            class="tool-select"
            :model-value="draft.apiKeyId"
            placeholder="选择 API Key"
            clearable
            filterable
            :disabled="generating"
            @change="$emit('update:api-key-id', $event || '')"
          >
            <el-option
              v-for="option in apiKeyOptions"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
          <el-select
            class="tool-select"
            :model-value="draft.model"
            placeholder="选择模型"
            clearable
            filterable
            allow-create
            default-first-option
            :loading="modelOptionsLoading"
            :disabled="generating || !draft.apiKeyId"
            @change="$emit('update:model-id', $event || '')"
          >
            <el-option
              v-for="option in modelOptions"
              :key="option"
              :label="option"
              :value="option"
            />
          </el-select>
        </div>
        <div class="toolbar-right">
          <button class="generate-action-btn" :disabled="!canSubmitPrompt || generating" @click="handleSubmitGeneration">
            <el-icon v-if="generating" class="is-loading"><Loading /></el-icon>
            <el-icon v-else><Top /></el-icon>
          </button>
        </div>
      </div>

      <button class="panel-delete-btn" @click="$emit('delete')">
        <el-icon><Delete /></el-icon>
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Delete, Document, Loading, Plus, Top } from '@element-plus/icons-vue'
import CanvasPromptMentionEditor from '@/components/canvas/CanvasPromptMentionEditor.vue'
import { useCanvasStudioCommitBoundary } from '@/composables/useCanvasStudioCommitBoundary'

const props = defineProps({
  item: { type: Object, default: null },
  style: { type: Object, default: null },
  draft: { type: Object, required: true },
  availableReferenceItems: { type: Array, default: () => [] },
  globalReferenceItems: { type: Array, default: () => [] },
  generating: { type: Boolean, default: false },
  apiKeyOptions: { type: Array, default: () => [] },
  modelOptions: { type: Array, default: () => [] },
  modelOptionsLoading: { type: Boolean, default: false }
})

const emit = defineEmits(['delete', 'drag-node', 'focus-item', 'handle-drag', 'submit-generation', 'update:api-key-id', 'update:model-id', 'update:text', 'update:title', 'update:tokens', 'commit'])

const promptEditorRef = ref(null)
const rootRef = ref(null)
const editableRef = ref(null)
const pendingEditorCardDrag = ref(null)
const canSubmitPrompt = computed(() => String(props.draft.promptPlainText || '').trim().length > 0)

const { handleRootPointerDown, handleRootFocusIn } = useCanvasStudioCommitBoundary(rootRef, () => {
  promptEditorRef.value?.flushTokens?.()
  emit('commit')
})

const handleSubmitGeneration = () => {
  promptEditorRef.value?.flushTokens?.()
  emit('submit-generation')
}

const handleHeaderPointerDown = (event) => {
  const interactiveTarget = event.target.closest('input, button, .el-select, .el-input')
  if (interactiveTarget) {
    return
  }
  emit('drag-node', event)
}

const clearPendingEditorCardDrag = () => {
  if (typeof window !== 'undefined' && pendingEditorCardDrag.value) {
    window.removeEventListener('mousemove', handleEditorCardPointerMove, true)
    window.removeEventListener('mouseup', handleEditorCardPointerUp, true)
  }
  pendingEditorCardDrag.value = null
}

const handleEditorCardPointerMove = (event) => {
  if (!pendingEditorCardDrag.value) {
    return
  }
  const deltaX = event.clientX - pendingEditorCardDrag.value.startX
  const deltaY = event.clientY - pendingEditorCardDrag.value.startY
  if (!pendingEditorCardDrag.value.triggered && Math.hypot(deltaX, deltaY) >= 5) {
    pendingEditorCardDrag.value = { ...pendingEditorCardDrag.value, triggered: true }
    emit('drag-node', event)
  }
}

const handleEditorCardPointerUp = () => {
  clearPendingEditorCardDrag()
}

const handleEditorCardPointerDown = (event) => {
  const interactiveTarget = event.target.closest('.rich-textarea, input, button, .el-select, .el-input')
  if (interactiveTarget) {
    return
  }
  pendingEditorCardDrag.value = {
    startX: event.clientX,
    startY: event.clientY,
    triggered: false
  }
  if (typeof window !== 'undefined') {
    window.addEventListener('mousemove', handleEditorCardPointerMove, true)
    window.addEventListener('mouseup', handleEditorCardPointerUp, true)
  }
}

const handleCardDragZonePointerDown = (event) => {
  pendingEditorCardDrag.value = {
    startX: event.clientX,
    startY: event.clientY,
    triggered: false
  }
  if (typeof window !== 'undefined') {
    window.addEventListener('mousemove', handleEditorCardPointerMove, true)
    window.addEventListener('mouseup', handleEditorCardPointerUp, true)
  }
}

const syncEditorHtml = async (html) => {
  if (!editableRef.value) {
    return
  }
  if (editableRef.value.innerHTML === String(html || '')) {
    return
  }
  editableRef.value.innerHTML = String(html || '')
  await nextTick()
}

const handleEditorInput = (event) => {
  emit('update:text', event.target.innerHTML)
}

const handleEditorBlur = (event) => {
  emit('update:text', event.target.innerHTML)
}

const flushDraft = () => {
  promptEditorRef.value?.flushTokens?.()
  if (editableRef.value) {
    emit('update:text', editableRef.value.innerHTML)
  }
}

watch(
  () => props.draft.text,
  (value) => {
    void syncEditorHtml(value)
  },
  { immediate: true }
)

onMounted(() => {
  void syncEditorHtml(props.draft.text)
})

onBeforeUnmount(() => {
  clearPendingEditorCardDrag()
})

defineExpose({
  flushDraft
})
</script>

<style scoped>
button {
  all: unset;
  box-sizing: border-box;
  cursor: pointer;
}

.canvas-text-studio-context {
  position: absolute;
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  pointer-events: none;
  z-index: 1000;
}

.floating-header,
.studio-docked-panel {
  pointer-events: auto;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 253, 0.98));
  border: 1px solid rgba(34, 57, 98, 0.1);
  backdrop-filter: blur(16px);
  box-shadow: 0 18px 34px rgba(34, 57, 98, 0.12);
}

.floating-header {
  position: absolute;
  top: var(--studio-header-top, -48px);
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  max-width: min(calc(100vw - 56px), 420px);
  gap: 12px;
  white-space: nowrap;
  padding: 6px 16px;
  border-radius: 999px;
  cursor: move;
}

.text-label {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #667085;
  font-size: 13px;
}

.header-title-input {
  background: transparent;
  border: none;
  outline: none;
  color: #1f2a44;
  font-size: 13px;
  font-weight: 600;
  width: 160px;
  min-width: 0;
}

.node-handle {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: auto;
}

.handle-left { left: -48px; }
.handle-right { right: -48px; }

.plus-icon {
  width: 28px;
  height: 28px;
  background: #fff;
  border: 1px solid rgba(75, 120, 255, 0.24);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #355ce0;
}

.editor-glass-card {
  position: absolute;
  inset: 0;
  pointer-events: auto;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(34, 57, 98, 0.1);
  border-radius: 24px;
  backdrop-filter: blur(28px);
  padding: 24px 28px;
  overflow: hidden;
}

.drag-strip {
  position: absolute;
  z-index: 2;
  pointer-events: auto;
}

.drag-strip--top,
.drag-strip--bottom {
  left: 24px;
  right: 24px;
  height: 14px;
  cursor: grab;
}

.drag-strip--top {
  top: 10px;
}

.drag-strip--bottom {
  bottom: 10px;
}

.drag-strip--left,
.drag-strip--right {
  top: 24px;
  bottom: 24px;
  width: 14px;
  cursor: grab;
}

.drag-strip--left {
  left: 10px;
}

.drag-strip--right {
  right: 10px;
}

.rich-textarea {
  position: relative;
  z-index: 1;
  width: 100%;
  height: 100%;
  outline: none;
  color: #1f2a44;
  font-size: 16px;
  line-height: 1.7;
  overflow-y: auto;
  word-break: break-word;
}

.rich-textarea :deep(h1),
.rich-textarea :deep(h2),
.rich-textarea :deep(h3) {
  margin: 0 0 12px;
  line-height: 1.3;
  letter-spacing: -0.01em;
}

.rich-textarea :deep(p),
.rich-textarea :deep(ul),
.rich-textarea :deep(ol) {
  margin: 0 0 10px;
}

.rich-textarea :deep(ul),
.rich-textarea :deep(ol) {
  padding-left: 20px;
}

.rich-textarea :deep(li) {
  margin: 0 0 6px;
}

.rich-textarea :deep(li:last-child) {
  margin-bottom: 0;
}

.rich-textarea :deep(blockquote) {
  margin: 0 0 12px;
  padding: 8px 12px;
  border-left: 3px solid rgba(75, 120, 255, 0.28);
  border-radius: 0 12px 12px 0;
  background: rgba(75, 120, 255, 0.06);
  color: #42526b;
}

.rich-textarea :deep(pre) {
  margin: 0 0 12px;
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(17, 24, 39, 0.05);
  color: #1f2a44;
  overflow: auto;
  white-space: pre-wrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
  line-height: 1.6;
}

.rich-textarea :deep(code) {
  padding: 0 4px;
  border-radius: 6px;
  background: rgba(17, 24, 39, 0.08);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.94em;
}

.rich-textarea :deep(a) {
  color: #355ce0;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.rich-textarea :deep(hr) {
  margin: 14px 0;
  border: none;
  border-top: 1px solid rgba(34, 57, 98, 0.12);
}

.rich-textarea :deep(strong) {
  color: #1f2a44;
}

.rich-textarea :deep(em) {
  color: #52607a;
}

.rich-textarea.is-empty::before {
  content: attr(data-placeholder);
  color: #98a2b3;
  pointer-events: none;
}

.studio-docked-panel {
  position: absolute;
  top: var(--studio-panel-top, calc(100% + 22px));
  bottom: var(--studio-panel-bottom, auto);
  left: 50%;
  transform: translateX(calc(-50% + var(--studio-panel-offset-x, 0px)));
  width: clamp(280px, calc(100vw - 64px), var(--studio-panel-max-width, 560px));
  min-width: min(var(--studio-panel-min-width, 360px), calc(100vw - 64px));
  max-width: calc(100vw - 64px);
  border-radius: 20px;
  padding: 14px 16px;
  box-shadow: 0 12px 48px -8px rgba(0, 0, 0, 0.55);
  max-height: min(320px, calc(100vh - 48px));
  overflow: visible;
}

.panel-toolbar,
.toolbar-left,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.panel-toolbar {
  margin-top: 14px;
  justify-content: space-between;
  flex-wrap: wrap;
}

.tool-select {
  width: 170px;
}

.generate-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 60px;
  height: 32px;
  padding: 0 14px;
  border-radius: 10px;
  background: linear-gradient(180deg, #4b78ff, #355ce0);
  color: #fff;
  font-weight: 700;
}

.panel-delete-btn {
  position: absolute;
  top: 12px;
  right: 14px;
  color: #98a2b3;
  width: 26px;
  height: 26px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}

@media (max-width: 720px) {
  .floating-header {
    gap: 8px;
    padding: 6px 12px;
  }

  .header-title-input {
    width: 120px;
  }

  .toolbar-left,
  .toolbar-right,
  .panel-toolbar {
    width: 100%;
  }

  .toolbar-left {
    flex-wrap: wrap;
  }

  .tool-select {
    flex: 1 1 160px;
    width: auto;
    min-width: 0;
  }

  .toolbar-right {
    justify-content: flex-end;
  }
}
</style>
