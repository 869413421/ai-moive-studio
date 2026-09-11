<template>
  <el-dialog
    v-model="dialogVisible"
    title="生成音频"
    width="500px"
  >
    <el-form :inline="false" class="dialog-form" label-width="80px">
      <el-form-item label="API Key">
        <el-select v-model="selectedApiKey" placeholder="选择API Key" style="width: 100%">
          <el-option
            v-for="key in apiKeys"
            :key="key.id"
            :label="`${key.name} (${key.provider})`"
            :value="key.id"
          />
        </el-select>
      </el-form-item>

      <el-form-item label="语音风格">
        <el-select 
          v-model="voice" 
          placeholder="选择语音风格" 
          style="width: 100%"
          filterable
          default-first-option
        >
          <el-option
            v-for="voiceOption in voiceOptions"
            :key="voiceOption.value"
            :label="voiceOption.label"
            :value="voiceOption.value"
          />
        </el-select>
      </el-form-item>

      <el-form-item label="模型">
        <el-select 
          v-model="model" 
          placeholder="选择模型" 
          style="width: 100%"
          :loading="loadingModels"
          filterable
          default-first-option
        >
          <el-option
            v-for="modelOption in modelOptions"
            :key="modelOption"
            :label="modelOption"
            :value="modelOption"
          />
        </el-select>
      </el-form-item>

      <div class="info-text">
        即将为 {{ sentencesCount }} 个句子生成音频。
      </div>
    </el-form>
    
    <template #footer>
      <span class="dialog-footer">
        <el-button @click="handleCancel">取消</el-button>
        <el-button type="primary" :loading="generating" @click="handleGenerate">
          生成
        </el-button>
      </span>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, defineProps, defineEmits, watch, computed } from 'vue'
import { ElMessage } from 'element-plus'
import audioService from '@/services/audio'
import api from '@/services/api'

const props = defineProps({
  visible: {
    type: Boolean,
    default: false
  },
  sentencesIds: {
    type: [Array, String],
    required: true
  },
  apiKeys: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['update:visible', 'generate-success'])

const dialogVisible = ref(props.visible)
const selectedApiKey = ref('')
const voice = ref('')
const model = ref('')
const modelOptions = ref([])
const loadingModels = ref(false)
const voiceOptions = ref([])
const generating = ref(false)

const catalogModels = ref([])

const sentencesCount = computed(() => {
  return Array.isArray(props.sentencesIds) ? props.sentencesIds.length : 1
})

// 监听visible prop变化，更新dialogVisible
watch(() => props.visible, (newValue) => {
  dialogVisible.value = newValue
})

watch(selectedApiKey, async (newKeyId, _, onCleanup) => {
  let current = true
  onCleanup(() => { current = false })
  modelOptions.value = []
  catalogModels.value = []
  model.value = ''
  voice.value = ''
  loadingModels.value = Boolean(newKeyId)
  if (!newKeyId) return
  try {
    const catalog = await api.get(`/api-keys/${newKeyId}/model-catalog`)
    if (!current) return
    catalogModels.value = (catalog.models || []).filter(m => m.type === 'audio')
    modelOptions.value = catalogModels.value.map(m => m.id)
    model.value = modelOptions.value.includes(catalog.defaults?.audio) ? catalog.defaults.audio : (modelOptions.value[0] || '')
  } catch (error) {
    if (current) ElMessage.warning('获取配音模型失败，请检查密钥')
  } finally {
    if (current) loadingModels.value = false
  }
})

watch(model, (newModel) => {
  const config = catalogModels.value.find(m => m.id === newModel)
  voiceOptions.value = (config?.voices || []).map(value => ({ label: value, value }))
  voice.value = config?.default_voice || ''
})

// 监听dialogVisible变化，通知父组件
watch(dialogVisible, (newValue) => {
  emit('update:visible', newValue)
})

// 更新visible状态并通知父组件
const updateDialogVisible = (newValue) => {
  dialogVisible.value = newValue
}

// 处理取消
const handleCancel = () => {
  updateDialogVisible(false)
  resetForm()
}

// 重置表单
const resetForm = () => {
  selectedApiKey.value = ''
  voice.value = ''
  model.value = ''
  modelOptions.value = []
  voiceOptions.value = []
}

// 处理生成音频
const handleGenerate = async () => {
  if (!selectedApiKey.value || !model.value || !voice.value || loadingModels.value) {
    ElMessage.warning('请选择可用的密钥、模型和音色')
    return
  }
  
  generating.value = true
  try {
    const ids = Array.isArray(props.sentencesIds) ? props.sentencesIds : [props.sentencesIds]
    const response = await audioService.generateAudio({
      sentences_ids: ids,
      api_key_id: selectedApiKey.value,
      voice: voice.value,
      model: model.value
    })
    
    if (response.success) {
      ElMessage.success(response.message)
      updateDialogVisible(false)
      emit('generate-success', response.task_id)
      // resetForm() // 成功后不重置，方便下次使用相同配置
    }
  } catch (error) {
    console.error('生成音频失败', error)
    ElMessage.error('生成音频失败: ' + (error.response?.data?.detail || error.message))
  } finally {
    generating.value = false
  }
}
</script>

<style scoped>
.dialog-form {
  margin-bottom: 0;
}

.info-text {
  margin-top: 10px;
  color: #909399;
  font-size: 14px;
  text-align: center;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-sm);
}
</style>
