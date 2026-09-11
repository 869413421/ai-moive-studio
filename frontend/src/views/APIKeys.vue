<template>
  <div class="api-keys-page">
    <div class="page-header">
      <div>
        <h1>API密钥管理</h1>
        <p>管理您的AI服务提供商API密钥</p>
      </div>
      <el-button type="primary" @click="showAddDialog">
        <el-icon><Plus /></el-icon>
        添加密钥
      </el-button>
    </div>

    <!-- 过滤器 -->
    <div class="filters-section">
      <el-select
        v-model="filterProvider"
        placeholder="服务提供商"
        clearable
        @change="loadAPIKeys"
        style="width: 180px"
      >
        <el-option label="全部提供商" value="" />
        <el-option
          v-for="provider in providerOptions"
          :key="provider.value"
          :label="provider.label"
          :value="provider.value"
        />
      </el-select>
      <el-select
        v-model="filterStatus"
        placeholder="状态"
        clearable
        @change="loadAPIKeys"
        style="width: 150px"
      >
        <el-option label="全部状态" value="" />
        <el-option
          v-for="status in apiKeyUtils.getStatusOptions()"
          :key="status.value"
          :label="status.label"
          :value="status.value"
        />
      </el-select>
    </div>

    <!-- API密钥列表 -->
    <el-table :data="apiKeys" v-loading="loading" class="api-keys-table">
      <el-table-column prop="name" label="名称" min-width="150">
        <template #default="{ row }">
          <div class="key-name">
            <el-icon><Key /></el-icon>
            <span>{{ row.name }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="provider" label="服务提供商" width="140">
        <template #default="{ row }">
          <el-tag type="info" size="small">
            {{ apiKeyUtils.getProviderName(row.provider) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="api_key" label="API密钥" min-width="180">
        <template #default="{ row }">
          <code class="api-key-display">{{ row.api_key }}</code>
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="apiKeyUtils.getStatusType(row.status)" size="small">
            {{ apiKeyUtils.getStatusText(row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="usage_count" label="使用次数" width="100" align="center">
        <template #default="{ row }">
          {{ apiKeyUtils.formatNumber(row.usage_count) }}
        </template>
      </el-table-column>
      <el-table-column prop="last_used_at" label="最后使用" width="160">
        <template #default="{ row }">
          {{ apiKeyUtils.formatDateTime(row.last_used_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="showEditDialog(row)" link>编辑</el-button>
          <el-button size="small" type="danger" @click="handleDelete(row)" link>删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div class="pagination-container">
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        @current-change="loadAPIKeys"
        @size-change="loadAPIKeys"
      />
    </div>

    <!-- 添加/编辑对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑API密钥' : '添加API密钥'"
      width="500px"
      :close-on-click-modal="false"
    >
      <el-form
        ref="formRef"
        :model="formData"
        :rules="formRules"
        label-width="100px"
      >
        <el-form-item label="名称" prop="name">
          <el-input
            v-model="formData.name"
            placeholder="请输入密钥名称"
            maxlength="100"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="服务提供商" prop="provider">
          <el-select
            v-model="formData.provider"
            @change="applyProviderPreset"
            placeholder="请选择服务提供商"
            :disabled="isEdit"
            style="width: 100%"
          >
            <el-option
              v-for="provider in providerOptions"
              :key="provider.value"
              :label="provider.label"
              :value="provider.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="API密钥" prop="api_key" v-if="!isEdit">
          <el-input
            v-model="formData.api_key"
            type="password"
            show-password
            placeholder="请输入API密钥"
          />
          <div class="form-tip">密钥将被加密存储，仅显示前4个字符</div>
        </el-form-item>
        <el-form-item label="Base URL" prop="base_url">
          <el-input
            v-model="formData.base_url"
            placeholder="留空使用所选供应商的默认地址"
          />
        </el-form-item>
        <el-form-item label="状态" prop="status" v-if="isEdit">
          <el-select v-model="formData.status" style="width: 100%">
            <el-option label="激活" value="active" />
            <el-option label="未激活" value="inactive" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSubmit" :loading="submitting">
          确定
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Key } from '@element-plus/icons-vue'
import { apiKeysService, apiKeyUtils } from '@/services/apiKeys'

const providerOptions = ref([])
const applyProviderPreset = (provider) => {
  formData.base_url = providerOptions.value.find(p => p.value === provider)?.base_url || ''
}

// 状态
const loading = ref(false)
const submitting = ref(false)
const apiKeys = ref([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const filterProvider = ref('')
const filterStatus = ref('')

// 对话框状态
const dialogVisible = ref(false)
const isEdit = ref(false)
const formRef = ref(null)
const formData = reactive({
  id: '',
  name: '',
  provider: '',
  api_key: '',
  base_url: '',
  status: 'active'
})

// 表单验证规则
const formRules = {
  name: [
    { required: true, message: '请输入密钥名称', trigger: 'blur' },
    { min: 1, max: 100, message: '名称长度在 1 到 100 个字符', trigger: 'blur' }
  ],
  provider: [
    { required: true, message: '请选择服务提供商', trigger: 'change' }
  ],
  api_key: [
    { required: true, message: '请输入API密钥', trigger: 'blur' }
  ]
}

// 加载API密钥列表
const loadAPIKeys = async () => {
  loading.value = true
  try {
    const params = {
      page: currentPage.value,
      size: pageSize.value
    }
    
    if (filterProvider.value) {
      params.provider = filterProvider.value
    }
    
    if (filterStatus.value) {
      params.key_status = filterStatus.value
    }
    
    const response = await apiKeysService.getAPIKeys(params)
    apiKeys.value = response.api_keys || []
    total.value = response.total || 0
  } catch (error) {
    console.error('加载API密钥失败:', error)
    ElMessage.error('加载API密钥失败')
  } finally {
    loading.value = false
  }
}

// 显示添加对话框
const showAddDialog = () => {
  isEdit.value = false
  Object.assign(formData, {
    id: '',
    name: '',
    provider: '',
    api_key: '',
    base_url: '',
    status: 'active'
  })
  dialogVisible.value = true
  
  // 重置表单验证
  if (formRef.value) {
    formRef.value.clearValidate()
  }
}

// 显示编辑对话框
const showEditDialog = (row) => {
  isEdit.value = true
  Object.assign(formData, {
    id: row.id,
    name: row.name,
    provider: row.provider,
    base_url: row.base_url || '',
    status: row.status
  })
  dialogVisible.value = true
  
  // 重置表单验证
  if (formRef.value) {
    formRef.value.clearValidate()
  }
}

// 提交表单
const handleSubmit = async () => {
  if (!formRef.value) return
  
  try {
    await formRef.value.validate()
  } catch (error) {
    return
  }
  
  submitting.value = true
  try {
    if (isEdit.value) {
      // 更新API密钥
      const updateData = {
        name: formData.name.trim(),
        base_url: formData.base_url.trim(),
        status: formData.status
      }
      await apiKeysService.updateAPIKey(formData.id, updateData)
      ElMessage.success('API密钥更新成功')
    } else {
      // 创建API密钥
      const createData = {
        name: formData.name.trim(),
        provider: formData.provider,
        api_key: formData.api_key,
        base_url: formData.base_url.trim() || null
      }
      await apiKeysService.createAPIKey(createData)
      ElMessage.success('API密钥添加成功')
    }
    
    dialogVisible.value = false
    await loadAPIKeys()
  } catch (error) {
    console.error('操作失败:', error)
    ElMessage.error(isEdit.value ? 'API密钥更新失败' : 'API密钥添加失败')
  } finally {
    submitting.value = false
  }
}

// 删除API密钥
const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除API密钥 "${row.name}" 吗？此操作不可恢复。`,
      '确认删除',
      {
        type: 'warning',
        confirmButtonText: '确定',
        cancelButtonText: '取消'
      }
    )
    
    await apiKeysService.deleteAPIKey(row.id)
    ElMessage.success('API密钥删除成功')
    await loadAPIKeys()
  } catch (error) {
    if (error !== 'cancel') {
      console.error('删除失败:', error)
      ElMessage.error('API密钥删除失败')
    }
  }
}

onMounted(async () => {
  loadAPIKeys()
  try {
    const presets = await apiKeysService.getProviderPresets()
    providerOptions.value = presets.map(p => ({ value: p.id, label: p.name, base_url: p.base_url }))
  } catch {
    ElMessage.warning('加载供应商选项失败，请刷新页面')
  }
})
</script>

<style scoped>
.api-keys-page {
  animation: fadeIn 0.3s ease-in-out;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
}

.page-header h1 {
  font-size: 28px;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--text-primary);
  letter-spacing: -0.5px;
}

.page-header p {
  color: var(--text-secondary);
  margin: 0;
  font-size: 14px;
}

.filters-section {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}

.api-keys-table {
  margin-bottom: 20px;
}

.key-name {
  display: flex;
  align-items: center;
  gap: 8px;
}

.key-name .el-icon {
  color: var(--primary-color);
}

.api-key-display {
  background: var(--bg-secondary);
  padding: 4px 8px;
  border-radius: 4px;
  font-family: 'Courier New', monospace;
  font-size: 12px;
  color: var(--text-primary);
  border: 1px solid var(--border-primary);
}

.pagination-container {
  display: flex;
  justify-content: flex-end;
  margin-top: 20px;
}

.form-tip {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 4px;
  line-height: 1.5;
}

:deep(.el-table) {
  border-radius: var(--radius-lg);
  overflow: hidden;
}

:deep(.el-table th) {
  background-color: var(--bg-secondary);
  color: var(--text-primary);
  font-weight: 600;
}

:deep(.el-table td) {
  color: var(--text-primary);
}

:deep(.el-table__empty-text) {
  color: var(--text-tertiary);
}

@media (max-width: 768px) {
  .page-header {
    flex-direction: column;
    gap: 16px;
  }

  .filters-section {
    flex-direction: column;
  }

  .filters-section .el-select {
    width: 100% !important;
  }
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
