/** @vitest-environment jsdom */
import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi } from 'vitest'
import Dialog from '@/components/studio/GenerateAudioDialog.vue'
import api from '@/services/api'
vi.mock('@/services/api', () => ({ default: { get: vi.fn() } }))
const select = { name: 'ElSelect', props: ['modelValue'], emits: ['update:modelValue'], template: '<div><slot /></div>' }
const slot = { template: '<div><slot /><slot name="footer" /></div>' }
const mountDialog = () => mount(Dialog, { props: { visible: true, apiKeys: [], sentencesIds: [] }, global: { stubs: {
  ElDialog: slot, ElForm: slot, ElFormItem: slot, ElSelect: select, ElOption: true, ElButton: true
} } })

describe('audio catalog selection', () => {
  it('uses each model voice list and ignores a late response for the previous key', async () => {
    let completeOld
    api.get.mockImplementation(url => url.includes('/old/') ? new Promise(resolve => { completeOld = resolve }) : Promise.resolve({ models: [
      { id: 'gemini-tts', type: 'audio', voices: ['Kore'], default_voice: 'Kore' },
      { id: 'speech-hd', type: 'audio', voices: ['female-tianmei'], default_voice: 'female-tianmei' }
    ] }))
    const wrapper = mountDialog()
    const selects = wrapper.findAllComponents({ name: 'ElSelect' })
    selects[0].vm.$emit('update:modelValue', 'old')
    await flushPromises()
    selects[0].vm.$emit('update:modelValue', 'new')
    await flushPromises()
    expect(selects[2].props('modelValue')).toBe('gemini-tts')
    expect(selects[1].props('modelValue')).toBe('Kore')
    selects[2].vm.$emit('update:modelValue', 'speech-hd')
    await flushPromises()
    expect(selects[1].props('modelValue')).toBe('female-tianmei')
    completeOld({ models: [{ id: 'wrong-key-model', type: 'audio' }] })
    await flushPromises()
    expect(selects[2].props('modelValue')).toBe('speech-hd')
    wrapper.unmount()
  })
})
