<template>
  <div
    ref="rootRef"
    class="canvas-image-studio-context"
    :style="style"
    @mousedown.stop
    @click.stop
    @wheel.stop
    @pointerdown.capture="handleRootPointerDown"
    @focusin="handleRootFocusIn"
  >
    <div class="floating-header" @mousedown.stop="handleHeaderPointerDown">
      <div class="image-label">
        <el-icon class="icon"><Picture /></el-icon>
        <span>图片节点</span>
      </div>
      <input :value="draft.title" class="header-title-input" placeholder="图片节点标题" @input="$emit('update:title', $event.target.value)" />
      <input ref="fileInputRef" class="image-upload-input" type="file" accept="image/*" @change="handleFileChange" />
      <button class="upload-btn" :disabled="uploading" @click="fileInputRef?.click()">
        <el-icon><Upload /></el-icon>
        <span>上传</span>
      </button>
    </div>

    <div class="image-preview-card" @mousedown.stop="handlePreviewPointerDown" @click="handlePreviewClick">
      <img v-if="previewUrl" :src="previewUrl" class="preview-image" alt="canvas preview" />
      <div v-else class="empty-preview">输入提示词或上传参考图</div>
      <CanvasGeneratingOverlay :visible="generating" label="AI 正在生成图像" hint="预计 30 秒至 2 分钟" />
    </div>

    <div class="node-handle handle-left" @mousedown.prevent="$emit('handle-drag', $event, 'left')">
      <div class="plus-icon"><el-icon><Plus /></el-icon></div>
    </div>
    <div class="node-handle handle-right" @mousedown.prevent="$emit('handle-drag', $event, 'right')">
      <div class="plus-icon"><el-icon><Plus /></el-icon></div>
    </div>

    <div class="studio-docked-panel">
      <CanvasPromptMentionEditor
        ref="promptEditorRef"
        :tokens="draft.promptTokens"
        :available-reference-items="availableReferenceItems"
        :global-reference-items="globalReferenceItems"
        prompt-placeholder="输入 prompt，可用 @ 引用节点"
        reference-picker-title="引用节点"
        :disabled="generating || uploading"
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
            :disabled="generating || uploading"
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
            :disabled="generating || uploading"
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
          <div class="toolbar-reference-group">
            <input
              ref="styleReferenceInputRef"
              class="image-upload-input"
              type="file"
              accept="image/*"
              @change="handleStyleReferenceFileChange"
            />
            <button
              class="toolbar-chip-btn"
              :class="{ 'is-active': hasStyleReference }"
              :disabled="generating || uploading"
              :title="hasStyleReference ? styleReferenceLabel : '上传风格参考图'"
              @click="styleReferenceInputRef?.click()"
            >
              <img
                v-if="draft.styleReferencePreviewUrl"
                :src="draft.styleReferencePreviewUrl"
                :alt="styleReferenceLabel"
                class="style-reference-thumb"
              />
              <el-icon v-else><Picture /></el-icon>
              <span>{{ hasStyleReference ? styleReferenceLabel : '风格参考' }}</span>
            </button>
            <button
              v-if="hasStyleReference"
              class="toolbar-ghost-btn"
              :disabled="generating || uploading"
              @click="$emit('clear-style-reference')"
            >
              清除
            </button>
          </div>
          <button v-if="draft.resultImageUrl" class="history-action-btn" @click="$emit('history')">历史</button>
          <button class="generate-action-btn" :disabled="!canSubmitPrompt || generating || uploading" @click="handleGenerate">
            <el-icon v-if="generating" class="is-loading"><Loading /></el-icon>
            <el-icon v-else><Top /></el-icon>
          </button>
        </div>
      </div>

      <button class="panel-delete-btn" @click="$emit('delete')">
        <el-icon><Delete /></el-icon>
      </button>
    </div>

    <el-dialog v-model="previewDialogVisible" width="min(96vw, 1080px)" append-to-body class="canvas-preview-dialog">
      <img v-if="previewUrl" :src="previewUrl" class="dialog-preview-image" alt="canvas full preview" />
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { Delete, Loading, Picture, Plus, Top, Upload } from '@element-plus/icons-vue'
import CanvasGeneratingOverlay from '@/components/canvas/CanvasGeneratingOverlay.vue'
import CanvasPromptMentionEditor from '@/components/canvas/CanvasPromptMentionEditor.vue'
import { useCanvasStudioCommitBoundary } from '@/composables/useCanvasStudioCommitBoundary'

const props = defineProps({
  style: { type: Object, default: null },
  draft: { type: Object, required: true },
  availableReferenceItems: { type: Array, default: () => [] },
  globalReferenceItems: { type: Array, default: () => [] },
  generating: { type: Boolean, default: false },
  uploading: { type: Boolean, default: false },
  apiKeyOptions: { type: Array, default: () => [] },
  modelOptions: { type: Array, default: () => [] },
  modelOptionsLoading: { type: Boolean, default: false }
})

const emit = defineEmits(['commit', 'delete', 'drag-node', 'focus-item', 'generate', 'handle-drag', 'history', 'update:api-key-id', 'update:model-id', 'update:title', 'update:tokens', 'upload', 'upload-style-reference', 'clear-style-reference'])

const promptEditorRef = ref(null)
const rootRef = ref(null)
const fileInputRef = ref(null)
const styleReferenceInputRef = ref(null)
const previewDialogVisible = ref(false)
const pendingPreviewDrag = ref(null)
const canSubmitPrompt = computed(() => String(props.draft.promptPlainText || '').trim().length > 0)
const previewUrl = computed(() => props.draft.resultImageUrl || props.draft.referenceImageUrl || '')
const hasStyleReference = computed(() => Boolean(String(props.draft.styleReferenceObjectKey || '').trim()))
const styleReferenceLabel = computed(() => String(props.draft.styleReferenceName || '').trim() || '已选择风格参考')

const { handleRootPointerDown, handleRootFocusIn } = useCanvasStudioCommitBoundary(rootRef, () => {
  promptEditorRef.value?.flushTokens?.()
  emit('commit')
})

const handleGenerate = () => {
  promptEditorRef.value?.flushTokens?.()
  emit('generate')
}

const handleFileChange = (event) => {
  const [file] = event.target.files || []
  if (file) {
    emit('upload', file)
  }
  event.target.value = ''
}

const handleStyleReferenceFileChange = (event) => {
  const [file] = event.target.files || []
  if (file) {
    emit('upload-style-reference', file)
  }
  event.target.value = ''
}

const handlePreviewClick = () => {
  if (pendingPreviewDrag.value?.triggered) {
    pendingPreviewDrag.value = null
    return
  }
  if (!previewUrl.value) {
    return
  }
  previewDialogVisible.value = true
}

const handleHeaderPointerDown = (event) => {
  const interactiveTarget = event.target.closest('input, button, .el-select, .el-input')
  if (interactiveTarget) {
    return
  }
  emit('drag-node', event)
}

const clearPendingPreviewDrag = () => {
  if (typeof window !== 'undefined' && pendingPreviewDrag.value) {
    window.removeEventListener('mousemove', handlePreviewPointerMove, true)
    window.removeEventListener('mouseup', handlePreviewPointerUp, true)
  }
  pendingPreviewDrag.value = null
}

const handlePreviewPointerMove = (event) => {
  if (!pendingPreviewDrag.value) {
    return
  }
  const deltaX = event.clientX - pendingPreviewDrag.value.startX
  const deltaY = event.clientY - pendingPreviewDrag.value.startY
  if (!pendingPreviewDrag.value.triggered && Math.hypot(deltaX, deltaY) >= 5) {
    pendingPreviewDrag.value = { ...pendingPreviewDrag.value, triggered: true }
    emit('drag-node', event)
  }
}

const handlePreviewPointerUp = () => {
  const triggered = pendingPreviewDrag.value?.triggered
  clearPendingPreviewDrag()
  if (triggered) {
    window.setTimeout(() => {
      pendingPreviewDrag.value = null
    }, 0)
  }
}

const handlePreviewPointerDown = (event) => {
  const interactiveTarget = event.target.closest('button, input, .el-button')
  if (interactiveTarget) {
    return
  }
  pendingPreviewDrag.value = {
    startX: event.clientX,
    startY: event.clientY,
    triggered: false
  }
  if (typeof window !== 'undefined') {
    window.addEventListener('mousemove', handlePreviewPointerMove, true)
    window.addEventListener('mouseup', handlePreviewPointerUp, true)
  }
}

onBeforeUnmount(() => {
  clearPendingPreviewDrag()
})

defineExpose({
  flushDraft: () => {
    promptEditorRef.value?.flushTokens?.()
  }
})
</script>

<style scoped>
.canvas-image-studio-context,
.canvas-video-studio-context {
  position: absolute;
  width: 100%;
  height: 100%;
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
  max-width: min(calc(100vw - 56px), 460px);
  gap: 12px;
  white-space: nowrap;
  padding: 6px 16px;
  border-radius: 999px;
  cursor: move;
}

.image-label {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #667085;
  font-size: 13px;
}

.header-title-input {
  width: 160px;
  min-width: 0;
  background: transparent;
  border: none;
  color: #1f2a44;
  font-size: 13px;
  font-weight: 600;
  outline: none;
}

.upload-btn,
.node-handle,
.studio-docked-panel,
.panel-delete-btn,
.image-preview-card {
  pointer-events: auto;
}

.image-upload-input { display: none; }

.upload-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: 14px;
  background: #eef4ff;
  color: #355ce0;
}

.image-preview-card {
  width: 100%;
  height: 100%;
  background: radial-gradient(circle at 30% 20%, rgba(75, 120, 255, 0.08), transparent 40%), #ffffff;
  backdrop-filter: blur(28px);
  border: 1px solid rgba(34, 57, 98, 0.1);
  border-radius: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  cursor: grab;
}

.image-preview-card:active {
  cursor: grabbing;
}

.preview-image {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.empty-preview {
  color: #98a2b3;
  font-size: 14px;
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

.studio-docked-panel {
  position: absolute;
  top: var(--studio-panel-top, calc(100% + 22px));
  bottom: var(--studio-panel-bottom, auto);
  left: 50%;
  transform: translateX(calc(-50% + var(--studio-panel-offset-x, 0px)));
  width: clamp(300px, calc(100vw - 64px), var(--studio-panel-max-width, 620px));
  min-width: min(var(--studio-panel-min-width, 420px), calc(100vw - 64px));
  max-width: calc(100vw - 64px);
  border-radius: 20px;
  padding: 14px 16px;
  max-height: min(360px, calc(100vh - 48px));
  overflow: visible;
}

.panel-toolbar,
.toolbar-left,
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.panel-toolbar {
  margin-top: 14px;
  justify-content: space-between;
  flex-wrap: nowrap;
}

.tool-select {
  width: 156px;
  min-width: 0;
}

.toolbar-left {
  flex: 1 1 auto;
  min-width: 0;
}

.toolbar-right {
  flex: 0 0 auto;
  justify-content: flex-end;
  flex-wrap: nowrap;
  min-width: 0;
}

.generate-action-btn,
.history-action-btn,
.toolbar-chip-btn,
.toolbar-ghost-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  height: 34px;
  padding: 0 12px;
  border-radius: 12px;
  white-space: nowrap;
}

.generate-action-btn {
  background: linear-gradient(180deg, #4b78ff, #355ce0);
  color: #fff;
  font-weight: 700;
}

.history-action-btn {
  background: rgba(255, 255, 255, 0.88);
  color: #355ce0;
  border: 1px solid rgba(75, 120, 255, 0.18);
}

.toolbar-reference-group {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 0 1 auto;
  padding: 4px 6px;
  border-radius: 12px;
  background: rgba(244, 247, 251, 0.92);
  border: 1px solid rgba(34, 57, 98, 0.08);
}

.toolbar-chip-btn {
  gap: 6px;
  max-width: 144px;
  background: rgba(238, 244, 255, 0.95);
  color: #355ce0;
  border: 1px solid rgba(75, 120, 255, 0.18);
  padding: 0 10px;
}

.toolbar-chip-btn.is-active {
  background: rgba(53, 92, 224, 0.1);
  border-color: rgba(53, 92, 224, 0.28);
}

.toolbar-chip-btn span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.toolbar-ghost-btn {
  background: rgba(255, 255, 255, 0.88);
  color: #667085;
  border: 1px solid rgba(34, 57, 98, 0.12);
  min-width: auto;
  padding: 0 10px;
  flex: 0 0 auto;
}

.history-action-btn {
  padding: 0 10px;
  flex: 0 0 auto;
}

.style-reference-thumb {
  width: 18px;
  height: 18px;
  border-radius: 6px;
  object-fit: cover;
  flex: 0 0 auto;
}

.panel-delete-btn {
  position: absolute;
  top: 10px;
  right: 12px;
  color: #98a2b3;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.dialog-preview-image {
  display: block;
  width: 100%;
  max-height: 80vh;
  object-fit: contain;
}

@media (max-width: 720px) {
  .floating-header {
    gap: 8px;
    padding: 6px 12px;
  }

  .header-title-input {
    width: 120px;
  }

  .panel-toolbar,
  .toolbar-left,
  .toolbar-right {
    width: 100%;
  }

  .panel-toolbar {
    flex-wrap: wrap;
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
    flex-wrap: wrap;
  }

  .toolbar-reference-group {
    width: 100%;
    justify-content: space-between;
  }
}
</style>
