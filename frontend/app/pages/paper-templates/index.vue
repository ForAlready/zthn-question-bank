<script setup lang="ts">
import PageHeader from '~/components/PageHeader.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Capability, usePermissions } from '~/composables/usePermissions'
import { fixedQuestionTypes } from '~/lib/fixedQuestionTypes'
import { apiErrorMessage } from '~/lib/apiError'
import type { PaperTemplate, TemplatePart, TemplateSection, TagFilter } from '~/types/paper'
import { toast } from 'vue-sonner'
const { $api } = useNuxtApp()
const { currentSubjectId } = useSubjectContext()
const { can } = usePermissions()
const canManage = computed(() => can(Capability.MANAGE_PAPER_TEMPLATE, currentSubjectId.value))
const templates = ref<PaperTemplate[]>([])
const selectedId = ref<number | null>(null)
const draft = ref<PaperTemplate | null>(null)
const busy = ref(false)
const dirty = ref(false)
const report = ref<any>(null)
const error = ref('')
const key = () => globalThis.crypto?.randomUUID?.() ?? 'r_' + Date.now() + Math.random().toString(36).slice(2)
const blankRule = (): TemplateSection => ({ key: key(), q_type: 'single_choice', tag_filter: { tag_ids: [], match: 'any' }, count: 1, score_each: 1 })
const total = computed(() => Math.round((draft.value?.parts.reduce((sum, part) => sum + part.sections.reduce((n, rule) => n + Number(rule.count) * Number(rule.score_each), 0), 0) ?? 0) * 10) / 10)
const mismatch = computed(() => Math.round(total.value * 10) !== Math.round(Number(draft.value?.total_score) * 10))
function changed() { dirty.value = true; report.value = null }
function syncScores() {
  if (!draft.value) return
  for (const part of draft.value.parts) part.part_score = Math.round(part.sections.reduce((n, s) => n + Number(s.count) * Number(s.score_each), 0) * 10) / 10
  changed()
}
async function load() {
  templates.value = []
  if (!currentSubjectId.value) return
  try { templates.value = await $api<PaperTemplate[]>('/paper-templates', { query: { subject_id: currentSubjectId.value } }) }
  catch (e) { error.value = apiErrorMessage(e, '模板加载失败') }
}
watch(currentSubjectId, async () => { selectedId.value = null; draft.value = null; dirty.value = false; report.value = null; await load() }, { immediate: true })
function select(t: PaperTemplate) {
  if (dirty.value && !confirm('当前修改未保存，确定切换？')) return
  selectedId.value = t.id
  draft.value = JSON.parse(JSON.stringify(t))
  if (!draft.value!.scope) draft.value!.scope = { tag_ids: [], match: 'any' }
  dirty.value = false; report.value = null; error.value = ''
}
function create() {
  if (!currentSubjectId.value) return
  selectedId.value = null
  draft.value = { id: 0, subject_id: currentSubjectId.value, name: '新模板', total_score: 1, enabled: true, is_system_default: false,
    scope: { tag_ids: [], match: 'any' }, duration_minutes: null, instructions: '',
    parts: [{ key: key(), title: '第一部分', part_score: 1, sections: [blankRule()] }] }
  dirty.value = true; report.value = null
}
function addPart() { draft.value?.parts.push({ key: key(), title: '新分区', part_score: 1, sections: [blankRule()] }); syncScores() }
async function save() {
  if (!draft.value || !currentSubjectId.value || mismatch.value) return
  busy.value = true; error.value = ''
  const d = draft.value
  const body = { name: d.name, total_score: Number(d.total_score), parts: d.parts, scope: d.scope, duration_minutes: d.duration_minutes || null, instructions: d.instructions, enabled: d.enabled }
  try {
    const result = await $api<PaperTemplate>(selectedId.value ? '/paper-templates/' + selectedId.value : '/paper-templates', {
      method: selectedId.value ? 'PATCH' : 'POST', body: selectedId.value ? body : { ...body, subject_id: currentSubjectId.value, schema_version: 2 },
    })
    dirty.value = false; await load(); select(result); toast.success('模板已保存')
  } catch (e) { error.value = apiErrorMessage(e, '保存失败') }
  finally { busy.value = false }
}
async function preflight() {
  if (!selectedId.value || dirty.value) { toast.error('请先保存模板'); return }
  busy.value = true
  try { report.value = await $api('/paper-templates/' + selectedId.value + '/preflight', { method: 'POST', body: { n_sets: 1, cross_set_dedup: true } }) }
  catch (e) { error.value = apiErrorMessage(e, '预检失败') }
  finally { busy.value = false }
}
async function restore() {
  if (!selectedId.value || !confirm('恢复此模板的默认规则？已生成试卷保持原快照。')) return
  busy.value = true
  try { const result = await $api<PaperTemplate>('/paper-templates/' + selectedId.value + '/restore-factory', { method: 'POST' }); dirty.value = false; await load(); select(result) }
  catch (e) { error.value = apiErrorMessage(e, '恢复失败') }
  finally { busy.value = false }
}
async function remove() {
  if (!selectedId.value || !confirm('确定删除当前模板？')) return
  try { await $api('/paper-templates/' + selectedId.value, { method: 'DELETE' }); draft.value = null; selectedId.value = null; await load() }
  catch (e) { error.value = apiErrorMessage(e, '删除失败') }
}
</script>
<template>
  <PageHeader title="组卷模板"><template #actions><Button v-if="canManage" @click="create">新建模板</Button></template></PageHeader>
  <div class="grid gap-6 p-6 lg:grid-cols-[260px_1fr]">
    <aside class="space-y-2"><button v-for="t in templates" :key="t.id" class="w-full rounded border p-3 text-left text-sm" :class="selectedId === t.id ? 'border-primary bg-primary/5' : ''" @click="select(t)">
      {{ t.name }} <span class="text-xs text-muted-foreground">{{ t.total_score }}分 {{ t.enabled ? '' : '已停用' }}</span>
    </button><p v-if="!templates.length" class="text-sm text-muted-foreground">当前学科暂无模板</p></aside>
    <main class="space-y-5">
      <p v-if="error" role="alert" class="rounded border border-destructive p-3 text-destructive">{{ error }}</p>
      <template v-if="draft">
        <div class="flex flex-wrap items-end gap-4 rounded border bg-card p-4">
          <label class="space-y-1 text-sm">模板名称<Input v-model="draft.name" :disabled="!canManage" @input="changed" /></label>
          <label class="w-28 space-y-1 text-sm">目标总分<Input v-model.number="draft.total_score" type="number" min="0.1" step="0.1" :disabled="!canManage" @input="changed" /></label>
          <span :class="mismatch ? 'text-destructive' : 'text-muted-foreground'">计算总分 {{ total }}分</span>
          <label class="text-sm"><input v-model="draft.enabled" type="checkbox" :disabled="!canManage" @change="changed" /> 启用</label>
          <span v-if="dirty" class="text-sm text-amber-700">未保存</span>
          <Button v-if="canManage" :disabled="busy || mismatch" @click="save">保存模板</Button>
          <Button variant="outline" :disabled="busy || dirty || !selectedId" @click="preflight">预检题池</Button>
          <Button v-if="canManage && draft.is_system_default" variant="outline" :disabled="busy" @click="restore">恢复默认</Button>
          <Button v-if="canManage && !draft.is_system_default && selectedId" variant="outline" @click="remove">删除模板</Button>
        </div>
        <div class="grid gap-3 sm:grid-cols-2"><label class="text-sm">考试时长（分钟，可选）<Input v-model.number="draft.duration_minutes" type="number" min="1" :disabled="!canManage" @input="changed" /></label><label class="text-sm">试卷说明<Input v-model="draft.instructions" :disabled="!canManage" @input="changed" /></label></div>
        <section class="rounded border p-4"><h2 class="mb-2 font-medium">全卷标签范围</h2>
          <TagCondition :model-value="draft.scope || { tag_ids: [], match: 'any' }" :subject-id="currentSubjectId" :disabled="!canManage" @update:model-value="draft.scope = $event; changed()" />
          <p class="mt-2 text-xs text-muted-foreground">全卷范围和每条抽题规则同时生效；标签分组不参与匹配。</p>
        </section>
        <section v-for="(part, pi) in draft.parts" :key="part.key" class="space-y-4 rounded border bg-card p-4">
          <div class="flex items-center gap-3"><Input v-model="part.title" aria-label="分区名称" :disabled="!canManage" @input="changed" /><span class="shrink-0">{{ part.part_score }}分</span>
            <Button v-if="canManage" variant="outline" @click="draft.parts.splice(pi, 1); syncScores()">删除分区</Button></div>
          <div v-for="(rule, ri) in part.sections" :key="rule.key" class="grid gap-3 rounded border bg-muted/20 p-3 xl:grid-cols-[110px_1fr_75px_90px_auto]">
            <label class="text-xs">题型<select v-model="rule.q_type" aria-label="规则题型" class="mt-1 h-9 w-full rounded border bg-background" :disabled="!canManage" @change="changed">
              <option v-for="t in fixedQuestionTypes" :key="t.value" :value="t.value">{{ t.label }}</option></select></label>
            <div><span class="text-xs">标签条件</span><TagCondition v-model="rule.tag_filter" :subject-id="currentSubjectId" :disabled="!canManage" @update:model-value="changed" /></div>
            <label class="text-xs">题量<Input v-model.number="rule.count" type="number" min="1" step="1" :disabled="!canManage" @input="syncScores" /></label>
            <label class="text-xs">每题分值<Input v-model.number="rule.score_each" type="number" min="0.1" step="0.1" :disabled="!canManage" @input="syncScores" /></label>
            <div class="space-y-2 text-xs"><p>小计 {{ Math.round(rule.count * rule.score_each * 10) / 10 }}分</p><Button v-if="canManage" size="sm" variant="outline" @click="part.sections.splice(ri, 1); syncScores()">删除规则</Button></div>
          </div>
          <Button v-if="canManage" variant="outline" @click="part.sections.push(blankRule()); syncScores()">添加抽题规则</Button>
        </section>
        <Button v-if="canManage" variant="outline" @click="addPart">添加分区</Button>
        <p v-if="mismatch" role="alert" class="text-destructive">计算总分与目标总分不一致，请调整后保存。</p>
        <section v-if="report" class="space-y-2 rounded border p-4">
          <h2 class="font-medium">{{ report.feasible ? '预检通过' : '题池不足或规则冲突' }}（{{ report.matched_slots }}/{{ report.required_slots }}题位）</h2>
          <p class="text-xs text-muted-foreground">预检不占用题目；生成时将重新校验。</p>
          <div v-for="r in report.rules" :key="r.section_key" class="text-sm">{{ r.part_key }} / {{ fixedQuestionTypes.find(t => t.value === r.q_type)?.label }}：需{{ r.count_per_set }}题，可用{{ r.candidate_count }}题</div>
          <p v-for="(g, i) in report.gaps" :key="i" class="text-sm text-destructive">{{ g.message }}</p>
        </section>
      </template><p v-else class="text-muted-foreground">选择模板查看规则，或新建模板。</p>
    </main>
  </div>
</template>
