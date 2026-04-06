function decodeHtmlEntities(value = '') {
  return String(value || '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
    .replace(/&#(\d+);/g, (_, code) => String.fromCharCode(Number(code)))
    .replace(/&#x([0-9a-f]+);/gi, (_, code) => String.fromCharCode(Number.parseInt(code, 16)))
}

function escapeHtml(value = '') {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function looksLikeRichTextHtml(value = '') {
  return /<\/?[a-z][\s\S]*>/i.test(String(value || ''))
}

function applyInlineMarkdown(value = '') {
  let html = escapeHtml(value)
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>')
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/(^|[^\*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>')
  return html
}

function convertMarkdownToRichHtml(value = '') {
  const lines = String(value || '').replace(/\r\n?/g, '\n').split('\n')
  const blocks = []
  let paragraphLines = []
  let listBuffer = null

  const flushParagraph = () => {
    if (!paragraphLines.length) {
      return
    }
    blocks.push(`<p>${paragraphLines.map((line) => applyInlineMarkdown(line)).join('<br>')}</p>`)
    paragraphLines = []
  }

  const flushList = () => {
    if (!listBuffer?.items?.length) {
      listBuffer = null
      return
    }
    const tag = listBuffer.ordered ? 'ol' : 'ul'
    blocks.push(`<${tag}>${listBuffer.items.map((item) => `<li>${applyInlineMarkdown(item)}</li>`).join('')}</${tag}>`)
    listBuffer = null
  }

  lines.forEach((line) => {
    const trimmed = line.trim()

    if (!trimmed) {
      flushParagraph()
      flushList()
      return
    }

    const headingMatch = trimmed.match(/^(#{1,3})\s+(.+)$/)
    if (headingMatch) {
      flushParagraph()
      flushList()
      const level = headingMatch[1].length
      blocks.push(`<h${level}>${applyInlineMarkdown(headingMatch[2])}</h${level}>`)
      return
    }

    const quoteMatch = trimmed.match(/^>\s?(.*)$/)
    if (quoteMatch) {
      flushParagraph()
      flushList()
      blocks.push(`<blockquote><p>${applyInlineMarkdown(quoteMatch[1])}</p></blockquote>`)
      return
    }

    const orderedMatch = trimmed.match(/^\d+\.\s+(.+)$/)
    if (orderedMatch) {
      flushParagraph()
      if (!listBuffer || !listBuffer.ordered) {
        flushList()
        listBuffer = { ordered: true, items: [] }
      }
      listBuffer.items.push(orderedMatch[1])
      return
    }

    const unorderedMatch = trimmed.match(/^[-*+]\s+(.+)$/)
    if (unorderedMatch) {
      flushParagraph()
      if (!listBuffer || listBuffer.ordered) {
        flushList()
        listBuffer = { ordered: false, items: [] }
      }
      listBuffer.items.push(unorderedMatch[1])
      return
    }

    flushList()
    paragraphLines.push(trimmed)
  })

  flushParagraph()
  flushList()
  return blocks.join('')
}

function convertPlainTextToRichHtml(value = '') {
  const normalized = String(value || '')
    .replace(/\r\n?/g, '\n')
    .trim()

  if (!normalized) {
    return ''
  }

  return normalized
    .split(/\n{2,}/)
    .map((paragraph) => {
      const content = paragraph
        .split('\n')
        .map((line) => escapeHtml(line))
        .join('<br>')
      return `<p>${content}</p>`
    })
    .join('')
}

function stripRichText(value = '') {
  let html = String(value || '')
    .replace(/\r\n?/g, '\n')
    .replace(/<\s*br\s*\/?\s*>/gi, '\n')
    .replace(/<li[^>]*>/gi, '\n• ')
    .replace(/<\/li>/gi, '\n')
    .replace(/<\/?(?:div|p|h[1-6]|blockquote|pre|section|article|header|footer)[^>]*>/gi, '\n')
    .replace(/<\/?(?:ul|ol)[^>]*>/gi, '\n')
    .replace(/<[^>]+>/g, '')

  html = decodeHtmlEntities(html)
  html = html
    .split('\n')
    .map((line) => line.replace(/\s+/g, ' ').trim())
    .filter(Boolean)
    .join('\n')

  return html.trim()
}

export const resolveCanvasRichTextHtml = (item) => {
  const value = String(item?.content?.text || item?.content?.draft_text || item?.content?.text_preview || item?.content?.prompt || '')
  if (!value.trim()) {
    return ''
  }
  if (looksLikeRichTextHtml(value)) {
    return value
  }
  if (/^\s*(#{1,3}\s|>\s|[-*+]\s|\d+\.\s|.*\*\*.*\*\*|.*`.+`)/m.test(value)) {
    return convertMarkdownToRichHtml(value)
  }
  return convertPlainTextToRichHtml(value)
}

export const resolveCanvasTextPreview = (item) =>
  stripRichText(item?.content?.text || item?.content?.draft_text || item?.content?.text_preview || item?.content?.prompt || '')

export const resolveCanvasStageMediaUrl = (item) => {
  if (!item) {
    return ''
  }
  if (item.item_type === 'image') {
    return String(item.content?.result_image_url || item.content?.reference_image_url || '').trim()
  }
  if (item.item_type === 'video') {
    return String(item.content?.result_video_url || '').trim()
  }
  return ''
}

const hasCanvasResultMedia = (item) => {
  if (!item) {
    return false
  }

  if (resolveCanvasStageMediaUrl(item)) {
    return true
  }

  if (item.item_type === 'image') {
    return Boolean(
      String(
        item.content?.result_image_object_key ||
        item.last_output?.result_image_object_key ||
        ''
      ).trim()
    )
  }

  if (item.item_type === 'video') {
    return Boolean(
      String(
        item.content?.result_video_object_key ||
        item.last_output?.result_video_object_key ||
        ''
      ).trim()
    )
  }

  return false
}

const defaultTranslate = (_key, fallback) => fallback
const normalizeRunStatus = (value) => String(value || '').trim().toLowerCase()

const summarizeErrorMessage = (value, t = defaultTranslate) => {
  const raw = String(value || '').trim()
  if (!raw) {
    return ''
  }

  try {
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed === 'object') {
      const nestedMessage = String(parsed.message || parsed.error || parsed.detail || '').trim()
      if (nestedMessage) {
        return summarizeErrorMessage(nestedMessage, t)
      }
    }
  } catch {
    // not json
  }

  const compact = raw.replace(/[{}"]/g, ' ').replace(/\s+/g, ' ').trim()
  if (compact.includes('生成过程中出现异常')) {
    return t('canvas.run_status_failed_generic', '生成过程中出现异常，请重试。')
  }
  if (/status fetch|temporary status failure|同步|重试/i.test(compact)) {
    return t('canvas.video_status_retrying_detail', '任务仍在运行，正在重试获取最新状态。')
  }
  if (compact.length <= 64) {
    return compact
  }
  return `${compact.slice(0, 64).trim()}...`
}

export const resolveCanvasRunStatusMeta = (item, t = defaultTranslate) => {
  if (!item || item.item_type === 'text') {
    return null
  }

  const status = normalizeRunStatus(item.last_run_status)
  const lastOutput = item.last_output || {}
  const transientStatusIssue = lastOutput?.transient_status_issue === true
  const errorMessage = summarizeErrorMessage(item?.last_run_error || lastOutput?.status_fetch_error || '', t)
  const hasMedia = hasCanvasResultMedia(item)

  if (transientStatusIssue) {
    return {
      tone: 'warning',
      label: t('canvas.video_status_retrying_label', '状态同步中'),
      detail: t('canvas.video_status_retrying_detail', '任务仍在运行，正在重试获取最新状态。')
    }
  }

  if (status === 'failed') {
    return {
      tone: 'error',
      label: t('canvas.video_status_failed_label', '生成失败'),
      detail: errorMessage || t('canvas.video_status_failed_detail', '生成任务失败，请重试。')
    }
  }

  if (status === 'completed') {
    return {
      tone: 'success',
      label: t('canvas.video_status_completed_label', item.item_type === 'video' ? '视频已生成' : '图片已生成'),
      detail: hasMedia
        ? t('canvas.video_status_completed_detail', item.item_type === 'video' ? '结果已就绪，可直接预览。' : '结果已就绪，可继续作为参考图使用。')
        : t('canvas.video_status_completed_syncing', '结果已完成，正在同步预览资源。')
    }
  }

  if (['processing', 'running'].includes(status)) {
    return {
      tone: 'info',
      label: t('canvas.video_status_processing_label', item.item_type === 'video' ? '视频生成中' : '图片生成中'),
      detail: t('canvas.video_status_processing_detail', item.item_type === 'video' ? '任务正在处理中，通常需要 2 至 10 分钟。' : '任务正在处理中，通常需要 30 秒至 2 分钟。')
    }
  }

  if (['pending', 'queued', 'submitted'].includes(status)) {
    return {
      tone: 'pending',
      label: t('canvas.video_status_pending_label', '任务已提交'),
      detail: t('canvas.video_status_pending_detail', '任务已入队，正在等待执行。')
    }
  }

  return null
}

export const isCanvasStageItemGenerating = (item) => {
  const status = String(item?.last_run_status || '').trim().toLowerCase()
  return ['pending', 'processing', 'running'].includes(status)
}

export const resolveCanvasStageGeneratingMeta = (item, t = defaultTranslate) => {
  if (!isCanvasStageItemGenerating(item)) {
    return null
  }

  if (item.item_type === 'image') {
    return {
      label: t('canvas.image_generating_label', 'AI 正在生成图像'),
      hint: t('canvas.image_generating_hint', '预计 30 秒至 2 分钟')
    }
  }

  if (item.item_type === 'video') {
    return {
      label: t('canvas.video_generating_label', 'AI 正在生成视频'),
      hint: t('canvas.video_generating_hint', '预计 2 至 10 分钟')
    }
  }

  return null
}

export const resolveCanvasStagePreviewText = (item, t = defaultTranslate) => {
  if (!item) {
    return ''
  }

  if (item.item_type === 'text') {
    return resolveCanvasTextPreview(item)
  }

  if (item.item_type === 'image') {
    if (resolveCanvasStageMediaUrl(item)) {
      return ''
    }
    return resolveCanvasRunStatusMeta(item, t)?.detail || t('canvas.image_result_pending', '等待图片结果')
  }

  if (item.item_type === 'video') {
    if (resolveCanvasStageMediaUrl(item)) {
      return resolveCanvasRunStatusMeta(item, t)?.detail || t('canvas.video_stage_generated', '已生成视频结果')
    }
    return resolveCanvasRunStatusMeta(item, t)?.detail || t('canvas.video_result_pending', '等待视频内容')
  }

  return ''
}

export const resolveCanvasRunErrorSummary = summarizeErrorMessage

export const resolveStageVideoPreviewTargets = ({ items = [], editingItemId = '' } = {}) =>
  items.filter((item) => item?.item_type === 'video' && String(item.id || '') !== String(editingItemId || ''))

export const releaseCanvasStageVideoEntry = (entry) => {
  const video = entry?.video
  if (!video) {
    return
  }

  video.onloadeddata = null
  video.onseeked = null
  video.onerror = null
  video.onloadedmetadata = null
  video.pause?.()
  if (typeof video.removeAttribute === 'function') {
    video.removeAttribute('src')
  } else if ('src' in video) {
    video.src = ''
  }
  video.load?.()
}
