<template>
  <div
    class="canvas-node"
    :class="[`type-${item.item_type}`, { selected }]"
    :style="nodeStyle"
    @mousedown.left.stop="$emit('drag-start', $event)"
    @click.stop="$emit('select')"
  >
    <button class="node-handle input" @click.stop="$emit('complete-connection')">
      <span></span>
    </button>
    <button class="node-handle output" @click.stop="$emit('start-connection')">
      <span></span>
    </button>

    <div class="node-header">
      <div>
        <div class="node-type">{{ typeLabel }}</div>
        <div class="node-title">{{ item.title || '未命名节点' }}</div>
      </div>
      <span class="node-status" :class="statusClass">{{ statusLabel }}</span>
    </div>

    <div class="node-body">
      <p v-if="item.item_type === 'text'" class="node-text">
        {{ item.content.text || item.content.draft_text || item.content.text_preview || item.content.prompt || '输入 prompt 后生成文本内容' }}
      </p>

      <div v-else-if="item.item_type === 'image'" class="media-preview">
        <img
          v-if="item.content.result_image_url || item.content.reference_image_url"
          :src="item.content.result_image_url || item.content.reference_image_url"
          alt="image preview"
        />
        <span v-else>生成图片或上传参考图</span>
      </div>

      <div v-else class="media-preview video">
        <video
          v-if="item.content.result_video_url"
          :src="item.content.result_video_url"
          controls
        ></video>
        <span v-else>生成视频后会在这里预览</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  item: {
    type: Object,
    required: true
  },
  selected: {
    type: Boolean,
    default: false
  }
})

defineEmits(['drag-start', 'select', 'start-connection', 'complete-connection'])

const nodeStyle = computed(() => ({
  width: `${props.item.width}px`,
  height: `${props.item.height}px`,
  transform: `translate(${props.item.position_x}px, ${props.item.position_y}px)`,
  zIndex: props.item.z_index
}))

const typeLabel = computed(() => {
  if (props.item.item_type === 'text') return 'Text'
  if (props.item.item_type === 'image') return 'Image'
  return 'Video'
})

const statusLabel = computed(() => {
  const status = props.item.last_run_status || 'idle'
  if (status === 'queued') return '队列中'
  if (status === 'running') return '生成中'
  if (status === 'succeeded') return '已生成'
  if (status === 'failed') return '失败'
  return '空闲'
})

const statusClass = computed(() => `status-${props.item.last_run_status || 'idle'}`)
</script>

<style scoped>
.canvas-node {
  position: absolute;
  border-radius: 18px;
  border: 1px solid rgba(32, 33, 36, 0.12);
  background: linear-gradient(180deg, #ffffff 0%, #f8f9fa 100%);
  box-shadow: 0 18px 32px rgba(32, 33, 36, 0.08);
  padding: 16px;
  cursor: grab;
  user-select: none;
  transition: box-shadow 0.2s ease, border-color 0.2s ease, transform 0.08s ease;
}

.canvas-node.selected {
  border-color: rgba(32, 33, 36, 0.45);
  box-shadow: 0 24px 44px rgba(32, 33, 36, 0.14);
}

.canvas-node:active {
  cursor: grabbing;
}

.node-handle {
  position: absolute;
  top: 50%;
  width: 22px;
  height: 22px;
  border: none;
  border-radius: 999px;
  background: transparent;
  transform: translateY(-50%);
  cursor: pointer;
}

.node-handle span {
  display: block;
  width: 12px;
  height: 12px;
  margin: 0 auto;
  border-radius: 999px;
  background: #202124;
  box-shadow: 0 0 0 3px rgba(32, 33, 36, 0.12);
}

.node-handle.input {
  left: -12px;
}

.node-handle.output {
  right: -12px;
}

.node-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.node-type {
  font-size: 11px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-tertiary);
}

.node-title {
  margin-top: 4px;
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.node-status {
  align-self: flex-start;
  padding: 6px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.status-idle {
  color: #5f6368;
  background: #eceff1;
}

.status-running,
.status-queued {
  color: #b06000;
  background: #fff3d6;
}

.status-succeeded {
  color: #0f6a36;
  background: #e8f3eb;
}

.status-failed {
  color: #b42318;
  background: #fce8e6;
}

.node-body {
  margin-top: 16px;
  height: calc(100% - 64px);
}

.node-text {
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
}

.media-preview {
  width: 100%;
  height: 100%;
  border-radius: 14px;
  background: #eef1f4;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  color: var(--text-tertiary);
  font-size: 13px;
}

.media-preview img,
.media-preview video {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.type-text {
  background: linear-gradient(180deg, #ffffff 0%, #f7f6f2 100%);
}

.type-image {
  background: linear-gradient(180deg, #ffffff 0%, #f2f6f8 100%);
}

.type-video {
  background: linear-gradient(180deg, #ffffff 0%, #f5f3f8 100%);
}
</style>
