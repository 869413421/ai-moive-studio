import { buildPromptDerivatives } from '@/utils/promptMentionTokens'

export const IMAGE_ASPECT_RATIO_OPTIONS = ['1:1', '3:4', '4:3', '16:9', '9:16']
export const VIDEO_ASPECT_RATIO_OPTIONS = ['16:9', '9:16', '1:1']
export const DEFAULT_ASPECT_RATIO = '16:9'

export const getSupportedVideoAspectRatios = (capabilities) => capabilities?.aspect_ratios || []

export const normalizeVideoAspectRatio = (capabilities, aspectRatio = '') => {
  const ratios = getSupportedVideoAspectRatios(capabilities)
  return ratios.includes(aspectRatio) ? aspectRatio : (ratios[0] || aspectRatio || DEFAULT_ASPECT_RATIO)
}

export const buildCanvasGenerationPayload = ({
  item,
  modelCapabilities,
  resolvedMentions = [],
  resolveImageReferenceObjectKey = (value) =>
    String(value?.object_key || value?.objectKey || '').trim(),
  resolveStyleReferenceImageObjectKey = (content = {}) =>
    String(content?.style_reference_image_object_key || '').trim()
} = {}) => {
  const content = item?.content || {}
  const promptTokens = Array.isArray(content.promptTokens)
    ? content.promptTokens
    : []
  const { promptPlainText } = buildPromptDerivatives(promptTokens)
  const payload = {
    prompt: promptPlainText || content.prompt || '',
    prompt_plain_text: promptPlainText || content.prompt || '',
    prompt_tokens: promptTokens,
    resolved_mentions: resolvedMentions,
    model: item?.generation_config?.model || undefined,
    api_key_id: item?.generation_config?.api_key_id || undefined,
    options: {}
  }

  if (item?.item_type === 'video') {
    const upstreamImageUrls = resolvedMentions
      .filter(
        (reference) =>
          reference.nodeType === 'image' && reference.status === 'resolved'
      )
      .map(
        (reference) =>
          reference.resolvedContent?.object_key ||
          reference.resolvedContent?.url ||
          ''
      )
      .filter(Boolean)

    if (upstreamImageUrls.length) {
      payload.options.reference_image_urls = upstreamImageUrls
    }

    const aspectRatio = normalizeVideoAspectRatio(
      modelCapabilities,
      item?.generation_config?.aspectRatio
    )
    if (aspectRatio) {
      payload.options.aspect_ratio = aspectRatio
    }
  } else if (item?.item_type === 'image') {
    const upstreamImageObjectKeys = resolvedMentions
      .filter(
        (reference) =>
          reference.nodeType === 'image' && reference.status === 'resolved'
      )
      .map((reference) =>
        resolveImageReferenceObjectKey(reference.resolvedContent)
      )
      .filter(Boolean)
    const styleReferenceImageObjectKey =
      resolveStyleReferenceImageObjectKey(content)
    const aspectRatio = String(content.aspectRatio || modelCapabilities?.aspect_ratios?.[0] || '').trim()

    if (upstreamImageObjectKeys.length) {
      payload.options.reference_image_object_keys = upstreamImageObjectKeys
    }
    if (styleReferenceImageObjectKey) {
      payload.options.style_reference_image_object_key =
        styleReferenceImageObjectKey
    }
    payload.options.aspect_ratio = aspectRatio || DEFAULT_ASPECT_RATIO
  }

  if (!Object.keys(payload.options).length) {
    delete payload.options
  }

  return payload
}
