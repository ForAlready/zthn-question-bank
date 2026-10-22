<script setup lang="ts">
import PageHeader from '~/components/PageHeader.vue'
import type { ExamPaperBatch, PaperTemplate } from '~/types'
import { apiErrorMessage } from '~/lib/apiError'
import { useAPI } from '~/composables/useAPI'
import { Capability, usePermissions } from '~/composables/usePermissions'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Loader2 } from '@lucide/vue'
import { toast } from 'vue-sonner'

const { $api } = useNuxtApp()
const router = useRouter()
const { currentSubjectId, hasSubjects } = useSubjectContext()
const { can } = usePermissions()
const canGenerate = computed(() => can(Capability.GENERATE_PAPER, currentSubjectId.value))

const {
  data: templates,
  refresh,
  status,
  error,
} = await useAPI<PaperTemplate[]>('/paper-templates', {
  query: computed(() => ({
    subject_id: currentSubjectId.value || undefined,
    enabled: true,
  })),
  immediate: false,
  watch: false,
})

watch(error, (err) => {
  if (err) toast.error(apiErrorMessage(err, '加载模板失败'))
})

watch(currentSubjectId, () => {
  if (currentSubjectId.value) refresh()
}, { immediate: true })

const form = ref({
  template_id: '' as string,
  title: '',
  n_sets: 1,
  cross_set_dedup: true,
})

watch(templates, (list) => {
  if (list?.length && !form.value.template_id) {
    form.value.template_id = String(list[0].id)
  }
})

const generating = ref(false)
const scopeMode = ref('inherit')
const customScope = ref({ tag_ids: [] as number[], match: 'any' as 'any' | 'all' })
const preview = ref<any>(null)
const lastGaps = ref<string[]>([])

watch(currentSubjectId, () => { form.value.template_id = ''; scopeMode.value = 'inherit'; customScope.value = {tag_ids:[],match:'any'}; preview.value = null })
const selectedTemplate = computed(() =>
  templates.value?.find((t) => String(t.id) === form.value.template_id) ?? null,
)

async function generate() {
  if (!form.value.template_id) {
    toast.error('请选择组卷模板')
    return
  }
  if (!canGenerate.value) {
    toast.error('当前学科无生成试卷权限')
    return
  }
  generating.value = true
  lastGaps.value = []
  try {
    const batch = await $api<ExamPaperBatch>('/exam-papers/generate', {
      method: 'POST',
      body: {
        template_id: Number(form.value.template_id),
        title: form.value.title.trim() || undefined,
        n_sets: form.value.n_sets,
        cross_set_dedup: form.value.cross_set_dedup,
        ...(scopeMode.value === 'inherit' ? {} : { scope: scopeMode.value === 'none' ? {tag_ids:[],match:'any'} : customScope.value }),
      },
    })
    toast.success(`已生成 ${batch.papers?.length ?? batch.n_sets} 套试卷`)
    const first = batch.papers?.[0]
    if (first) {
      await router.push(`/exam-papers/${first.id}`)
    }
  } catch (e) {
    const detail = (e as { data?: { detail?: { message?: string; gaps?: unknown[] } } })?.data?.detail
    if (detail && typeof detail === 'object' && Array.isArray(detail.gaps)) {
      lastGaps.value = detail.gaps.map((g) =>
        typeof g === 'string' ? g : String((g as any)?.message ?? JSON.stringify(g)),
      )
    }
    toast.error(apiErrorMessage(e, '生成试卷失败'))
  } finally {
    generating.value = false
  }
}
async function preflight() {
  if (!form.value.template_id) return
  generating.value = true
  try {
    preview.value = await $api('/paper-templates/' + form.value.template_id + '/preflight', {
      method: 'POST', body: { n_sets: form.value.n_sets, cross_set_dedup: form.value.cross_set_dedup,
        ...(scopeMode.value === 'inherit' ? {} : {scope:scopeMode.value === 'none' ? {tag_ids:[],match:'any'} : customScope.value}) },
    })
  } catch (e) { toast.error(apiErrorMessage(e,'预检失败')) }
  finally { generating.value = false }
}
</script>

<template>
  <div class="mx-6 mt-6 space-y-3 rounded border p-4">
    <label class="text-sm">全卷标签范围
      <select v-model="scopeMode" class="ml-3 h-9 rounded border bg-background px-2">
        <option value="inherit">沿用模板范围</option><option value="custom">临时指定</option><option value="none">本次不限制</option>
      </select>
    </label>
    <TagCondition v-if="scopeMode === 'custom'" v-model="customScope" :subject-id="currentSubjectId" />
    <p class="text-xs text-muted-foreground">范围仅影响本批，与每条规则同时生效，不修改模板。</p>
    <Button variant="outline" :disabled="generating || !form.template_id" @click="preflight">预检当前条件</Button>
    <div v-if="preview" class="space-y-1 text-sm">
      <p>{{ preview.feasible ? '预检通过' : '预检未通过' }}：{{ preview.matched_slots }}/{{ preview.required_slots }} 题位</p>
      <p v-for="(g,i) in preview.gaps" :key="i" class="text-destructive">{{ g.message }}</p>
    </div>
  </div>
  <PageHeader title="试卷">
    <template #actions>
      <Button
        :disabled="!hasSubjects || !canGenerate || generating || !form.template_id"
        @click="generate"
      >
        <Loader2 v-if="generating" class="mr-2 size-4 animate-spin" />
        {{ generating ? '生成中…' : '生成试卷' }}
      </Button>
    </template>
  </PageHeader>

  <div class="flex flex-1 flex-col">
    <div class="mx-auto grid w-full max-w-[1360px] flex-1 gap-6 px-4 py-6 lg:grid-cols-[360px_1fr] md:px-8">
      <div v-if="!hasSubjects" class="col-span-full rounded-[var(--qb-radius-panel)] border bg-card p-10 text-center text-muted-foreground">
        请先选择学科后再生成试卷。
      </div>

      <template v-else>
        <aside class="rounded-[var(--qb-radius-panel)] border bg-card p-5">
          <h2 class="text-base font-semibold">生成条件</h2>
          <p class="mt-1 text-xs text-muted-foreground">
            选择模板与平行卷套数。套间去重默认开启。
          </p>

          <div v-if="status === 'pending'" class="flex justify-center py-10">
            <Loader2 class="size-6 animate-spin text-muted-foreground" />
          </div>

          <div v-else-if="!templates?.length" class="py-10 text-center text-sm text-muted-foreground">
            暂无启用中的组卷模板，请先在「组卷模板」中配置。
          </div>

          <div v-else class="mt-5 space-y-4">
            <div class="space-y-2">
              <Label>组卷模板 <span class="text-destructive">*</span></Label>
              <Select v-model="form.template_id">
                <SelectTrigger class="h-9">
                  <SelectValue placeholder="选择模板" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="t in templates" :key="t.id" :value="String(t.id)">
                    {{ t.name }}（{{ t.total_score }} 分）
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div class="space-y-2">
              <Label>试卷标题</Label>
              <Input v-model="form.title" placeholder="可选，默认使用模板名称" />
            </div>

            <div class="space-y-2">
              <Label>平行卷套数</Label>
              <Input v-model.number="form.n_sets" type="number" min="1" max="10" class="h-9" />
              <p class="text-xs text-muted-foreground">
                超过 1 套时，去重设置影响整个批次。
              </p>
            </div>

            <div class="flex items-start justify-between gap-4 rounded-[var(--qb-radius-control)] border bg-qb-surface-subtle p-3">
              <div>
                <Label>套间不重复用题</Label>
                <p class="mt-1 text-xs text-muted-foreground">
                  {{ form.cross_set_dedup
                    ? '开启：同批各套之间不重复用题。'
                    : '关闭：每套内部仍不重复，不同套之间可重复。' }}
                </p>
              </div>
              <Switch
                :model-value="form.cross_set_dedup"
                @update:model-value="form.cross_set_dedup = $event"
              />
            </div>

            <div
              v-if="!canGenerate"
              class="rounded-[var(--qb-radius-control)] border border-[color:var(--qb-danger)] bg-[color:var(--qb-danger-soft)] px-3 py-2 text-sm text-[color:var(--qb-danger)]"
            >
              当前角色无「生成试卷」权限。
            </div>

            <Button
              class="w-full"
              :disabled="!canGenerate || generating || !form.template_id"
              @click="generate"
            >
              <Loader2 v-if="generating" class="mr-2 size-4 animate-spin" />
              {{ generating ? '生成中…' : '生成试卷' }}
            </Button>
          </div>
        </aside>

        <section class="rounded-[var(--qb-radius-panel)] border bg-card p-5">
          <h2 class="text-base font-semibold">题池校验摘要</h2>
          <p class="mt-1 text-xs text-muted-foreground">
            生成前请确认模板规则与题库覆盖；不足时系统会返回缺口说明。
          </p>

          <div v-if="selectedTemplate" class="mt-4 space-y-3">
            <div class="rounded-[var(--qb-radius-control)] border bg-qb-surface-subtle p-3 text-sm">
              <div class="font-medium">{{ selectedTemplate.name }}</div>
              <div class="mt-1 tabular-nums text-muted-foreground">
                总分 {{ selectedTemplate.total_score }} ·
                {{ selectedTemplate.parts?.length ?? 0 }} 个分区 ·
                {{ selectedTemplate.duration_minutes ? `${selectedTemplate.duration_minutes} 分钟` : '未设时长' }}
              </div>
              <ul class="mt-3 space-y-1 text-xs text-muted-foreground">
                <li v-for="(part, i) in selectedTemplate.parts" :key="part.key + i">
                  {{ part.title }}：{{ part.sections.length }} 条题型规则 · 分区 {{ part.part_score }} 分
                </li>
              </ul>
            </div>

            <div
              v-if="lastGaps.length"
              class="rounded-[var(--qb-radius-control)] border border-[color:var(--qb-danger)] bg-[color:var(--qb-danger-soft)] px-3 py-2 text-sm text-[color:var(--qb-danger)]"
            >
              <p class="font-medium">题池不足，本批次无法生成：</p>
              <ul class="mt-1 list-inside list-disc text-xs">
                <li v-for="(g, i) in lastGaps" :key="i">{{ g }}</li>
              </ul>
            </div>
            <div v-else class="text-sm text-muted-foreground">
              点击「生成试卷」后将校验题池；成功后进入试卷预览。
            </div>
          </div>
          <div v-else class="mt-8 text-center text-sm text-muted-foreground">
            选择模板后显示规则摘要。
          </div>
        </section>
      </template>
    </div>
  </div>
</template>
