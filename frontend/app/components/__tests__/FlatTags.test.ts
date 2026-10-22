import { afterEach, describe, expect, it, vi } from 'vitest'
import { createApp, defineComponent, h, nextTick, ref, computed, watch } from 'vue'
import FlatTagSelect from '../FlatTagSelect.vue'
import TagCondition from '../TagCondition.vue'

const apps: ReturnType<typeof createApp>[] = []
const flush = async () => { await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() }
afterEach(() => { apps.forEach(app => app.unmount()); apps.length = 0; document.body.innerHTML = ''; vi.unstubAllGlobals() })
function mount(component: any, props: () => any, api: any) {
  vi.stubGlobal('ref', ref); vi.stubGlobal('computed', computed); vi.stubGlobal('watch', watch)
  vi.stubGlobal('useNuxtApp', () => ({ $api: api }))
  const app = createApp(defineComponent({ setup: () => () => h(component, props()) }))
  app.component('FlatTagSelect', FlatTagSelect)
  apps.push(app)
  const root = document.createElement('div'); document.body.append(root); app.mount(root)
  return root
}
describe('扁平标签真实交互', () => {
  it('多选回显、搜索、停用标签只允许移除', async () => {
    const ids = ref([3])
    const api = vi.fn(async () => ({ items: [{ id: 1, name: '业务', enabled: true }, { id: 2, name: '处置', enabled: false }, { id: 3, name: '旧标签', enabled: false }] }))
    const root = mount(FlatTagSelect, () => ({ subjectId: 1, modelValue: ids.value, 'onUpdate:modelValue': (v: number[]) => { ids.value = v } }), api)
    await flush()
    const candidates = () => [...root.querySelectorAll<HTMLButtonElement>('[aria-pressed]')]
    expect(candidates()[1]!.disabled).toBe(true)
    expect(candidates()[2]!.disabled).toBe(false)
    candidates()[0]!.click(); await flush(); expect(ids.value).toEqual([3, 1])
    candidates()[2]!.click(); await flush(); expect(ids.value).toEqual([1])
    const input = root.querySelector('input')!; input.value = '业务'; input.dispatchEvent(new Event('input')); await flush()
    expect(candidates()).toHaveLength(1)
    expect(candidates()[0]!.getAttribute('aria-pressed')).toBe('true')
  })
  it('切换全部匹配保留多选值，清空标签明确显示不限制', async () => {
    const filter = ref({ tag_ids: [1, 2], match: 'any' })
    const root = mount(TagCondition, () => ({ subjectId: 1, modelValue: filter.value, 'onUpdate:modelValue': (v: any) => { filter.value = v } }), async () => ({ items: [] }))
    await flush()
    const select = root.querySelector('select')!; select.value = 'all'; select.dispatchEvent(new Event('change')); await flush()
    expect(filter.value).toEqual({ tag_ids: [1, 2], match: 'all' })
    expect(root.textContent).toContain('同时包含以上全部标签')
    filter.value = { tag_ids: [], match: 'all' }; await flush()
    expect(root.textContent).toContain('不限制标签')
  })
  it('加载失败可重试，切换学科不会采用过期响应', async () => {
    let resolveOld: (v: any) => void = () => {}
    const subject = ref(1)
    const api = vi.fn().mockRejectedValueOnce(new Error('network'))
      .mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
      .mockResolvedValueOnce({ items: [{ id: 2, name: '新学科标签', enabled: true }] })
    const root = mount(FlatTagSelect, () => ({ subjectId: subject.value, modelValue: [] }), api)
    await flush(); expect(root.textContent).toContain('加载失败')
    root.querySelector('button')!.click(); await flush()
    subject.value = 2; await flush(); resolveOld({ items: [{ id: 1, name: '过期标签' }] }); await flush()
    expect(root.textContent).toContain('新学科标签'); expect(root.textContent).not.toContain('过期标签')
  })
})
