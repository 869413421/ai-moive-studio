// Models are always scoped to one credential and one operation.
export const modelsFor = (catalog, keyId, type) =>
  (catalog?.connections?.[keyId]?.models || []).filter(model => model.type === type && model.available && model.enabled)

export const defaultSelection = (catalog, keys, type) => {
  for (const key of keys) {
    const models = modelsFor(catalog, key.value, type)
    if (!models.length) continue
    const preferred = catalog.connections[key.value].defaults?.[type]
    return { api_key_id: key.value, model: models.find(m => m.id === preferred)?.id || models[0].id }
  }
  return {}
}

export const modelFor = (catalog, item) => modelsFor(catalog, item?.generation_config?.api_key_id, item?.item_type)
  .find(model => model.id === item?.generation_config?.model)
