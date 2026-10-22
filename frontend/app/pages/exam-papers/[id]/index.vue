<script setup lang="ts">
import PageHeader from '~/components/PageHeader.vue'
import RichContent from '~/components/rich-editor/RichContent.vue'
import type { ExamPaper, ExamPaperBatch, ExamPaperExportMode, ExamPaperItem } from '~/types'
import { apiErrorMessage } from '~/lib/apiError'
import { richDocToPlainText } from '~/components/rich-editor/richDoc'
import type { RichDoc } from '~/types'
import { Capability, usePermissions } from '~/composables/usePermissions'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ArrowLeft, Download, Loader2, RefreshCw, Replace, Lock } from '@lucide/vue'
import { toast } from 'vue-sonner'
import { fixedQuestionTypes } from '~/lib/fixedQuestionTypes'
const typeName = (type: string) => fixedQuestionTypes.find(t => t.value === type)?.label || type

const route = useRoute()
const router = useRouter()
const { $api } = useNuxtApp()
const { can } = usePermissions()

const paperId = computed(() => Number(route.params.id))
const paper = ref<ExamPaper | null>(null)
const batch = ref<ExamPaperBatch | null>(null)
const loading = ref(true)
const busy = ref(false)

const canEdit = computed(() =>
  !!paper.value && can(Capability.GENERATE_PAPER, paper.value.subject_id),
)
const canExportPlain = computed(() =>
  !!paper.value && can(Capability.EXPORT_PAPER_WITHOUT_ANSWERS, paper.value.subject_id),
)
const canExportAnswers = computed(() =>
  !!paper.value && can(Capability.EXPORT_WITH_ANSWERS, paper.value.subject_id),
)
const isFinal = computed(() => paper.value?.status === 'final')

// 与出卷时的模板快照比较，避免模板后续修改改变本卷的总分基准。
const templateTotal = computed(() => {
  const snap = paper.value?.template_snapshot_json as { total_score?: number } | undefined
  return snap?.total_score ?? null
})

const scoreWarning = computed(() => {
  if (!paper.value || templateTotal.value == null) return false
  return Math.abs(paper.value.actual_total_score - templateTotal.value) > 0.01
})

function stemText(item: ExamPaperItem): string {
  const content = item.content_snapshot_json?.content as RichDoc | undefined
  return richDocToPlainText(content) || '（无题干）'
}

function optionLabel(opt: { label?: string; content?: unknown }, index: number): string {
  const label = opt.label || String.fromCharCode(65 + index)
  const text = richDocToPlainText(opt.content as RichDoc)
  return `${label}. ${text || '（空）'}`
}

async function loadPaper() {
  if (!paperId.value || Number.isNaN(paperId.value)) return
  loading.value = true
  try {
    paper.value = await $api<ExamPaper>(`/exam-papers/${paperId.value}`)
    if (paper.value?.batch_id) {
      try {
        batch.value = await $api<ExamPaperBatch>(`/exam-papers/batches/${paper.value.batch_id}`)
      } catch {
        batch.value = null
      }
    }
  } catch (e) {
    paper.value = null
    toast.error(apiErrorMessage(e, '加载试卷失败'))
  } finally {
    loading.value = false
  }
}

watch(paperId, () => loadPaper(), { immediate: true })

async function updateScore(item: ExamPaperItem, raw: string | number) {
  if (!paper.value || isFinal.value || !canEdit.value) return
  const score = Number(raw)
  if (!score || score <= 0) {
    toast.error('分值必须大于 0')
    return
  }
  if (score === item.score) return
  busy.value = true
  try {
    paper.value = await $api<ExamPaper>(`/exam-papers/${paper.value.id}/items/${item.id}`, {
      method: 'PATCH',
      body: { score },
    })
    toast.success('分值已更新')
  } catch (e) {
    toast.error(apiErrorMessage(e, '更新分值失败'))
    await loadPaper()
  } finally {
    busy.value = false
  }
}

async function replaceRandom(item: ExamPaperItem) {
  if (!paper.value || isFinal.value || !canEdit.value) return
  busy.value = true
  try {
    paper.value = await $api<ExamPaper>(
      `/exam-papers/${paper.value.id}/items/${item.id}/replace`,
      {
        method: 'POST',
        body: { mode: 'random_same_type' },
      },
    )
    toast.success('已随机换题')
  } catch (e) {
    toast.error(apiErrorMessage(e, '换题失败'))
  } finally {
    busy.value = false
  }
}

const manualOpen = ref(false)
const manualItem = ref<ExamPaperItem | null>(null)
function replaceManual(item: ExamPaperItem) {
  manualItem.value = item
  manualOpen.value = true
}

async function reshuffle() {
  if (!paper.value || isFinal.value || !canEdit.value) return
  if (!confirm('确定重抽整卷题目？当前题目与分值将被替换。')) return
  busy.value = true
  try {
    paper.value = await $api<ExamPaper>(`/exam-papers/${paper.value.id}/reshuffle`, {
      method: 'POST',
    })
    toast.success('已重抽试卷')
  } catch (e) {
    toast.error(apiErrorMessage(e, '重抽失败'))
  } finally {
    busy.value = false
  }
}

async function finalize() {
  if (!paper.value || isFinal.value || !canEdit.value) return
  if (!confirm('定稿后题目与分值将锁定，仍可导出。确定定稿？')) return
  busy.value = true
  try {
    paper.value = await $api<ExamPaper>(`/exam-papers/${paper.value.id}/finalize`, {
      method: 'POST',
    })
    toast.success('试卷已定稿')
  } catch (e) {
    toast.error(apiErrorMessage(e, '定稿失败'))
  } finally {
    busy.value = false
  }
}

// --- Export dialog ---
const exportOpen = ref(false)
const exportMode = ref<ExamPaperExportMode>('without_answers')
const includeAnalysis = ref(false)
const exporting = ref(false)

function openExport() {
  if (!canExportPlain.value && !canExportAnswers.value) {
    toast.error('无导出权限')
    return
  }
  exportMode.value = canExportPlain.value ? 'without_answers' : 'with_answers'
  includeAnalysis.value = false
  exportOpen.value = true
}

async function doExport() {
  if (!paper.value) return
  if (exportMode.value === 'with_answers' && !canExportAnswers.value) {
    toast.error('无「导出有答案卷」权限')
    return
  }
  if (exportMode.value === 'without_answers' && !canExportPlain.value) {
    toast.error('无「导出无答案卷」权限')
    return
  }
  exporting.value = true
  try {
    const blob = await $api<Blob>(`/exam-papers/${paper.value.id}/export`, {
      method: 'POST',
      body: {
        mode: exportMode.value,
        include_analysis: exportMode.value === 'with_answers' ? includeAnalysis.value : false,
      },
      responseType: 'blob',
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${paper.value.title || '试卷'}-${exportMode.value === 'with_answers' ? '有答案' : '无答案'}.docx`
    a.click()
    URL.revokeObjectURL(url)
    toast.success('导出已开始下载')
    exportOpen.value = false
  } catch (e) {
    toast.error(apiErrorMessage(e, '导出失败（若后端尚未开放导出接口，请稍后重试）'))
  } finally {
    exporting.value = false
  }
}

const itemsByPart = computed(() => {
  const map = new Map<string, ExamPaperItem[]>()
  for (const item of paper.value?.items || []) {
    const key = item.part_key || 'default'
    if (!map.has(key)) map.set(key, [])
    map.get(key)!.push(item)
  }
  for (const list of map.values()) {
    list.sort((a, b) => a.seq - b.seq)
  }
  return map
})

function partTitle(key: string): string {
  const snap = paper.value?.template_snapshot_json as {
    parts?: Array<{ key: string; title: string }>
  } | undefined
  return snap?.parts?.find((p) => p.key === key)?.title || key
}
</script>

<template>
  <PageHeader :title="paper?.title || '试卷预览'">
    <template #actions>
      <Button variant="outline" size="sm" @click="router.push('/exam-papers')">
        <ArrowLeft class="mr-1.5 size-3.5" />
        返回生成
      </Button>
      <Button
        v-if="canEdit && !isFinal"
        variant="outline"
        size="sm"
        :disabled="busy"
        @click="reshuffle"
      >
        <RefreshCw class="mr-1.5 size-3.5" />
        重抽
      </Button>
      <Button
        v-if="canEdit && !isFinal"
        variant="outline"
        size="sm"
        :disabled="busy"
        @click="finalize"
      >
        <Lock class="mr-1.5 size-3.5" />
        定稿
      </Button>
      <Button size="sm" :disabled="!paper" @click="openExport">
        <Download class="mr-1.5 size-3.5" />
        导出
      </Button>
    </template>
  </PageHeader>

  <div class="flex flex-1 flex-col">
    <div class="mx-auto w-full max-w-[1360px] flex-1 px-4 py-6 md:px-8">
      <div v-if="loading" class="flex justify-center py-20">
        <Loader2 class="size-8 animate-spin text-muted-foreground" />
      </div>

      <div v-else-if="!paper" class="rounded-[var(--qb-radius-panel)] border bg-card p-10 text-center text-muted-foreground">
        试卷不存在或加载失败。
        <div class="mt-4">
          <Button variant="outline" @click="loadPaper">重新加载</Button>
        </div>
      </div>

      <template v-else>
        <div class="mb-4 flex flex-wrap items-center gap-3 rounded-[var(--qb-radius-panel)] border bg-card px-4 py-3">
          <Badge :variant="isFinal ? 'default' : 'secondary'">
            {{ isFinal ? '已定稿' : '草稿' }}
          </Badge>
          <span class="text-sm tabular-nums">
            实际总分 {{ paper.actual_total_score }}
            <template v-if="templateTotal != null"> / 模板 {{ templateTotal }}</template>
          </span>
          <span class="text-sm text-muted-foreground">套别 {{ paper.set_index }}</span>
          <div v-if="batch?.papers?.length && batch.papers.length > 1" class="ml-auto flex flex-wrap gap-1">
            <Button
              v-for="p in batch.papers"
              :key="p.id"
              size="sm"
              :variant="p.id === paper.id ? 'default' : 'outline'"
              @click="router.push(`/exam-papers/${p.id}`)"
            >
              第 {{ p.set_index }} 套
            </Button>
          </div>
        </div>

        <div
          v-if="scoreWarning"
          class="mb-4 rounded-[var(--qb-radius-control)] border border-[color:var(--qb-warning)] bg-[color:var(--qb-warning-soft)] px-3 py-2 text-sm text-[color:var(--qb-warning)]"
        >
          当前总分 {{ paper.actual_total_score }} 分，模板总分 {{ templateTotal }} 分。可以继续保存和导出，导出卷面将以实际总分显示。
        </div>

        <div
          v-if="isFinal"
          class="mb-4 rounded-[var(--qb-radius-control)] border bg-[color:var(--qb-info-soft)] px-3 py-2 text-sm text-[color:var(--qb-info)]"
        >
          试卷已定稿，题目和分值已锁定。仍可导出无答案卷或有答案卷。
        </div>

        <div v-if="paper.template_warnings?.length" role="alert" class="mb-4 rounded border border-amber-400 bg-amber-50 p-3 text-sm text-amber-900">
          <p class="font-medium">当前试卷与模板存在偏差</p>
          <p v-for="warning in paper.template_warnings" :key="warning">{{ warning }}</p>
        </div>
        <div class="space-y-8 rounded-[var(--qb-radius-panel)] border bg-card p-5 md:p-8">
          <div v-for="[partKey, items] in itemsByPart" :key="partKey" class="space-y-4">
            <h2 class="text-lg font-semibold">{{ partTitle(partKey) }}</h2>
            <template v-for="(item, itemIndex) in items" :key="item.id">
            <h3 v-if="itemIndex === 0 || items[itemIndex - 1]?.q_type !== item.q_type" class="font-semibold">{{ typeName(item.q_type) }}（{{ items.filter(i => i.q_type === item.q_type).length }} 题）</h3>
            <article
              class="border-b border-border pb-5 last:border-0"
            >
              <div class="flex flex-wrap items-start gap-3">
                <div class="min-w-0 flex-1">
                  <div class="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span class="tabular-nums font-medium text-foreground">第 {{ item.seq }} 题</span>
                    <span v-if="item.q_type">{{ typeName(item.q_type) }}</span>
                  </div>
                  <div class="mb-2 flex flex-wrap gap-2"><span v-for="cat in (item.tag_snapshot_json as { id: number; name: string }[] ?? [])" :key="cat.id" class="rounded border px-2 py-0.5 text-xs">{{ cat.name }}</span></div>
                  <RichContent :content="item.content_snapshot_json?.content as RichDoc" empty-text="（无题干）" />
                  <ul
                    v-if="item.content_snapshot_json?.options?.length"
                    class="mt-2 space-y-1 text-sm text-muted-foreground"
                  >
                    <li
                      v-for="(opt, oi) in item.content_snapshot_json.options"
                      :key="opt.id || oi"
                    >
                      <div class="flex gap-2"><span>{{ opt.label || String.fromCharCode(65 + oi) }}.</span><RichContent :content="opt.content as RichDoc" empty-text="（空选项）" /></div>
                    </li>
                  </ul>
                </div>

                <div class="flex shrink-0 flex-col items-end gap-2">
                  <div class="flex items-center gap-2">
                    <Label class="text-xs text-muted-foreground">分值</Label>
                    <Input
                      class="h-8 w-20 tabular-nums"
                      type="number"
                      min="0.1"
                      step="0.1"
                      :model-value="item.score"
                      :disabled="isFinal || !canEdit || busy"
                      @change="updateScore(item, ($event.target as HTMLInputElement).value)"
                    />
                  </div>
                  <div v-if="!isFinal && canEdit" class="flex gap-1">
                    <Button
                      variant="outline"
                      size="sm"
                      :disabled="busy"
                      @click="replaceRandom(item)"
                    >
                      <Replace class="mr-1 size-3.5" />
                      随机同类题
                    </Button>
                    <Button variant="ghost" size="sm" :disabled="busy" @click="replaceManual(item)">
                      手动选题
                    </Button>
                  </div>
                </div>
              </div>
            </article>
            </template>
          </div>

          <div v-if="!paper.items?.length" class="py-10 text-center text-sm text-muted-foreground">
            本卷暂无题目。
          </div>
        </div>
      </template>
    </div>
  </div>

  <Dialog v-model:open="exportOpen">
    <DialogContent class="rounded-[var(--qb-radius-panel)] sm:max-w-md">
      <DialogHeader>
        <DialogTitle>导出试卷</DialogTitle>
        <DialogDescription>
          选择导出模式。有答案卷默认不包含解析；答案从新页开始。
        </DialogDescription>
      </DialogHeader>

      <RadioGroup v-model="exportMode" class="space-y-3 py-2">
        <label
          class="flex cursor-pointer items-start gap-3 rounded-[var(--qb-radius-control)] border p-3"
          :class="!canExportPlain ? 'opacity-50' : ''"
        >
          <RadioGroupItem value="without_answers" :disabled="!canExportPlain" class="mt-0.5" />
          <div>
            <div class="text-sm font-medium">无答案卷</div>
            <p class="text-xs text-muted-foreground">仅卷面题目，适合考生使用。</p>
          </div>
        </label>
        <label
          class="flex cursor-pointer items-start gap-3 rounded-[var(--qb-radius-control)] border p-3"
          :class="!canExportAnswers ? 'opacity-50' : ''"
        >
          <RadioGroupItem value="with_answers" :disabled="!canExportAnswers" class="mt-0.5" />
          <div>
            <div class="text-sm font-medium">有答案卷</div>
            <p class="text-xs text-muted-foreground text-[color:var(--qb-warning)]">
              含答案内容，请注意保密。默认不包含解析。
            </p>
          </div>
        </label>
      </RadioGroup>

      <div class="flex items-center gap-2 py-1">
        <Checkbox
          id="include-analysis"
          :checked="includeAnalysis"
          :disabled="exportMode !== 'with_answers'"
          @update:checked="(v) => includeAnalysis = !!v"
        />
        <Label for="include-analysis" class="text-sm">包含解析</Label>
      </div>

      <DialogFooter>
        <Button variant="outline" @click="exportOpen = false">取消</Button>
        <Button :disabled="exporting" @click="doExport">
          <Loader2 v-if="exporting" class="mr-2 size-4 animate-spin" />
          确认导出
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
  <ManualReplacementDialog v-if="paper" v-model:open="manualOpen" :paper="paper" :item="manualItem" @updated="paper = $event" />
</template>
