/**
 * API密钥管理服务 - 严格按照规范实现
 */

import { get, post, put, del } from './api'

/**
 * API密钥管理服务
 */
export const apiKeysService = {
    /**
     * 获取API密钥列表
     * @param {Object} params - 查询参数
     * @param {number} params.page - 页码
     * @param {number} params.size - 每页大小
     * @param {string} params.provider - 服务提供商过滤
     * @param {string} params.key_status - 状态过滤
     * @returns {Promise} API密钥列表和总数
     */
    async getAPIKeys(params = {}) {
        return await get('/api-keys/', { params })
    },

    /**
     * 根据ID获取API密钥详情
     * @param {string} keyId - 密钥ID
     * @returns {Promise} API密钥详情
     */
    async getAPIKey(keyId) {
        return await get(`/api-keys/${keyId}`)
    },

    /**
     * 创建新API密钥
     * @param {Object} keyData - 密钥数据
     * @param {string} keyData.name - 密钥名称
     * @param {string} keyData.provider - 服务提供商
     * @param {string} keyData.api_key - API密钥
     * @param {string} keyData.base_url - API基础URL（可选）
     * @returns {Promise} 创建的API密钥
     */
    async createAPIKey(keyData) {
        return await post('/api-keys/', keyData)
    },

    /**
     * 更新API密钥
     * @param {string} keyId - 密钥ID
     * @param {Object} updateData - 更新数据
     * @param {string} updateData.name - 密钥名称
     * @param {string} updateData.base_url - API基础URL
     * @param {string} updateData.status - 状态
     * @returns {Promise} 更新后的API密钥
     */
    async updateAPIKey(keyId, updateData) {
        return await put(`/api-keys/${keyId}`, updateData)
    },

    /**
     * 删除API密钥
     * @param {string} keyId - 密钥ID
     * @returns {Promise} 删除结果
     */
    async deleteAPIKey(keyId) {
        return await del(`/api-keys/${keyId}`)
    },

    /**
     * 获取API密钥使用统计
     * @param {string} keyId - 密钥ID
     * @returns {Promise} 使用统计
     */
    async getAPIKeyUsage(keyId) {
        return await get(`/api-keys/${keyId}/usage`)
    },

    /**
     * 获取API密钥支持的模型列表
     * @param {string} keyId - 密钥ID
     * @returns {Promise} 模型列表
     */
    async getAPIKeyModels(keyId, type = null) {
        const params = type ? { type } : {}
        return await get(`/api-keys/${keyId}/models`, { params })
    }
}

/**
 * API密钥工具 - 简洁实现，匹配后端数据模型
 */
export const apiKeyUtils = {
    /**
     * 获取服务提供商显示名称
     * @param {string} provider - 提供商标识
     * @returns {string} 显示名称
     */
    getProviderName(provider) {
        const providerMap = {
            'openai': 'OpenAI',
            'azure': 'Azure OpenAI',
            'google': 'Google AI',
            'baidu': '百度文心',
            'alibaba': '阿里云',
            'volcengine': '火山引擎',
            'custom': '自定义',
            'siliconflow': 'SiliconFlow',
            'twelvelabs': 'TwelveLabs'
        }
        return providerMap[provider] || provider
    },

    /**
     * 获取状态文本
     * @param {string} status - 状态值
     * @returns {string} 状态文本
     */
    getStatusText(status) {
        const statusMap = {
            'active': '激活',
            'inactive': '未激活',
            'expired': '已过期'
        }
        return statusMap[status] || status
    },

    /**
     * 获取状态类型（用于UI组件）
     * @param {string} status - 状态值
     * @returns {string} Element Plus状态类型
     */
    getStatusType(status) {
        const typeMap = {
            'active': 'success',
            'inactive': 'info',
            'expired': 'danger'
        }
        return typeMap[status] || 'info'
    },

    /**
     * 获取提供商图标
     * @param {string} provider - 提供商标识
     * @returns {string} 图标名称
     */
    getProviderIcon(provider) {
        const iconMap = {
            'openai': 'ChatDotRound',
            'azure': 'Cloudy',
            'google': 'Search',
            'baidu': 'Search',
            'alibaba': 'Cloudy',
            'volcengine': 'Cloudy',
            'custom': 'Setting',
            'siliconflow': 'Cloudy',
            'twelvelabs': 'VideoCamera'
        }
        return iconMap[provider] || 'Key'
    },

    /**
     * 格式化时间
     * @param {string} dateTime - 时间字符串
     * @returns {string} 格式化的时间
     */
    formatDateTime(dateTime) {
        if (!dateTime) return '-'
        const date = new Date(dateTime)
        return date.toLocaleString('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
        })
    },

    /**
     * 格式化数字
     * @param {number} num - 数字
     * @returns {string} 格式化后的数字
     */
    formatNumber(num) {
        if (num === null || num === undefined) return '0'
        return num.toLocaleString()
    },

    /**
     * 获取提供商列表
     * @returns {Array} 提供商选项列表
     */
    getProviderOptions() {
        return [
            // { label: 'OpenAI', value: 'openai' },
            // { label: 'Azure OpenAI', value: 'azure' },
            // { label: 'Google AI', value: 'google' },
            // { label: '百度文心', value: 'baidu' },
            // { label: '阿里云', value: 'alibaba' },
            // { label: '火山引擎', value: 'volcengine' },
            // { label: 'deepseek', value: 'deepseek' },
            { label: '硅基流动', value: 'siliconflow' },
            { label: 'TwelveLabs (视频理解 / 向量)', value: 'twelvelabs' },
            { label: '自定义', value: 'custom' }
        ]
    },

    /**
     * 获取状态选项列表
     * @returns {Array} 状态选项列表
     */
    getStatusOptions() {
        return [
            { label: '激活', value: 'active' },
            { label: '未激活', value: 'inactive' },
            { label: '已过期', value: 'expired' }
        ]
    }
}

export default apiKeysService
