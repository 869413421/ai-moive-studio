<template>
  <div
    ref="rootRef"
    class="canvas-video-studio-context"
    :style="style"
    @mousedown.stop
    @click.stop
    @wheel.stop
    @pointerdown.capture="handleRootPointerDown"
    @focusin="handleRootFocusIn"
  >
    <div class="floating-header" @mousedown.stop="handleHeaderPointerDown">
      <div class="image-label">
        <el-icon class="icon"><VideoCamera /></el-icon>
        <span>视频节点</span>
      </div>
      <input :value="draft.title" class="header-title-input" placeholder="视频节点标题" @input="$emit('update:title', $event.target.value)" />
      <input ref="fileInputRef" class="image-upload-input" type="file" accept="video/*" @change="handleFileChange" />
      <button class="upload-btn" :disabled="uploading" @click="fileInputRef?.click()">
        <el-icon><Upload /></el-icon>
        <span>上传</span>
      </button>
    </div>

    <div class="image-preview-card" @mousedown.stop="handlePreviewPointerDown" @click="handlePreviewClick">
      <video v-if="draft.resultVideoUrl" :src="draft.resultVideoUrl" class="preview-image" controls playsinline preload="metadata"></video>
      <div v-else class="empty-preview">输入提示词并连接上游参考节点</div>
      <CanvasGeneratingOverlay :visible="generating" label="AI 正在生成视频" hint="预计 2 至 10 分钟" />
    </div>

    <div class="node-handle handle-left" @mousedown.prevent="$emit('handle-drag', $event, 'left')">
      <div class="plus-icon"><el-icon><Plus /></el-icon></div>
    </div>
    <div class="node-handle handle-right" @mousedown.prevent="$emit('handle-drag', $event, 'right')">
      <div class="plus-icon"><el-icon><Plus /></el-icon></div>
    </div>

    <div class="studio-docked-panel">
      <div v-if="statusMeta" class="status-banner" :class="`status-banner--${statusMeta.tone}`">
        <div class="status-banner__label">{{ statusMeta.label }}</div>
        <div class="status-banner__detail">{{ statusMeta.detail }}</div>
      </div>
      <CanvasPromptMentionEditor
        ref="promptEditorRef"
        :tokens="draft.promptTokens"
        :available-reference-items="availableReferenceItems"
        :global-reference-items="globalReferenceItems"
        prompt-placeholder="输入 prompt，可用 @ 引用节点"
        reference-picker-title="引用节点"
        :helper-text="referenceHintText"
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
          <button v-if="draft.resultVideoUrl" class="history-action-btn" @click="$emit('history')">历史</button>
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
      <video
        v-if="draft.resultVideoUrl"
        :src="draft.resultVideoUrl"
        class="dialog-preview-video"
        controls
        autoplay
        playsinline
        preload="metadata"
      ></video>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { Delete, Loading, Plus, Top, Upload, VideoCamera } from '@element-plus/icons-vue'
import CanvasGeneratingOverlay from '@/components/canvas/CanvasGeneratingOverlay.vue'
import CanvasPromptMentionEditor from '@/components/canvas/CanvasPromptMentionEditor.vue'
import { useCanvasStudioCommitBoundary } from '@/composables/useCanvasStudioCommitBoundary'

const props = defineProps({
  style: { type: Object, default: null },
  draft: { type: Object, required: true },
  availableReferenceItems: { type: Array, default: () => [] },
  globalReferenceItems: { type: Array, default: () => [] },
  referenceHintText: { type: String, default: '' },
  statusMeta: { type: Object, default: null },
  generating: { type: Boolean, default: false },
  uploading: { type: Boolean, default: false },
  apiKeyOptions: { type: Array, default: () => [] },
  modelOptions: { type: Array, default: () => [] },
  modelOptionsLoading: { type: Boolean, default: false }
})

const emit = defineEmits(['commit', 'delete', 'drag-node', 'focus-item', 'generate', 'handle-drag', 'history', 'update:api-key-id', 'update:model-id', 'update:title', 'update:tokens', 'upload'])

const promptEditorRef = ref(null)
const rootRef = ref(null)
const fileInputRef = ref(null)
const previewDialogVisible = ref(false)
const pendingPreviewDrag = ref(null)
const canSubmitPrompt = computed(() => String(props.draft.promptPlainText || '').trim().length > 0)

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

const handlePreviewClick = () => {
  if (pendingPreviewDrag.value?.triggered) {
    pendingPreviewDrag.value = null
    return
  }
  if (!props.draft.resultVideoUrl) {
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

.image-upload-input { display: none; }

.upload-btn,
.node-handle,
.studio-docked-panel,
.panel-delete-btn,
.image-preview-card {
  pointer-events: auto;
}

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
  object-fit: cover;
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
  border-radius: 20px;
  padding: 14px 16px;
  max-height: min(360px, calc(100vh - 48px));
  overflow: visible;
}

.status-banner {
  margin-bottom: 12px;
  padding: 10px 12px;
  border-radius: 14px;
  border: 1px solid transparent;
  background: rgba(248, 250, 253, 0.92);
}

.status-banner__label {
  font-size: 12px;
  font-weight: 700;
}

.status-banner__detail {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.5;
  color: #52607a;
}

.status-banner--info {
  background: rgba(238, 244, 255, 0.96);
  border-color: rgba(75, 120, 255, 0.18);
}

.status-banner--info .status-banner__label {
  color: #355ce0;
}

.status-banner--pending,
.status-banner--warning {
  background: rgba(255, 248, 235, 0.96);
  border-color: rgba(245, 158, 11, 0.24);
}

.status-banner--pending .status-banner__label,
.status-banner--warning .status-banner__label {
  color: #b7791f;
}

.status-banner--success {
  background: rgba(238, 249, 242, 0.96);
  border-color: rgba(34, 197, 94, 0.22);
}

.status-banner--success .status-banner__label {
  color: #15803d;
}

.status-banner--error {
  background: rgba(254, 242, 242, 0.96);
  border-color: rgba(239, 68, 68, 0.2);
}

.status-banner--error .status-banner__label {
  color: #dc2626;
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
  flex-wrap: wrap;
}

.tool-select {
  width: 170px;
}

.generate-action-btn,
.history-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 64px;
  height: 34px;
  padding: 0 14px;
  border-radius: 12px;
}

.generate-action-btn {
  background: linear-gradient(180deg, #4b78ff, #355ce0);
  color: #fff;
  font-weight: 700;
}

.history-action-btn {
  background: #eef4ff;
  color: #355ce0;
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

.dialog-preview-video {
  display: block;
  width: 100%;
  max-height: 80vh;
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
