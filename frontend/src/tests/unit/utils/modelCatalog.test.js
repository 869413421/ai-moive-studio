import { describe, it, expect } from 'vitest'
import { modelsFor, defaultSelection, modelFor } from '@/utils/modelCatalog'
import { buildCanvasGenerationPayload } from '@/utils/canvasGenerationPayload'

const model = (id, type, extra = {}) => ({ id, type, available: true, enabled: true, ...extra })
const catalog = { connections: {
  first: { models: [model('text-only', 'text')] },
  second: { models: [model('image-b', 'image', { aspect_ratios: ['1:1', '3:2'] }), model('hidden', 'image', { enabled: false })] }
} }

describe('credential-scoped model selection', () => {
  it('never combines a model from one key with another key', () => {
    expect(modelsFor(catalog, 'first', 'image')).toEqual([])
    expect(defaultSelection(catalog, [{ value: 'first' }, { value: 'second' }], 'image')).toEqual({ api_key_id: 'second', model: 'image-b' })
    expect(modelFor(catalog, { item_type: 'image', generation_config: { api_key_id: 'first', model: 'image-b' } })).toBeUndefined()
  })
  it('excludes hidden models and uses selected capabilities for ratios', () => {
    expect(modelsFor(catalog, 'second', 'image')).toHaveLength(1)
    const payload = buildCanvasGenerationPayload({
      item: { item_type: 'image', content: { prompt: 'draw' } },
      modelCapabilities: modelsFor(catalog, 'second', 'image')[0]
    })
    expect(payload.options.aspect_ratio).toBe('1:1')
  })
})
