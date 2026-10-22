<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { ExamPaper, ExamPaperItem, RichDoc } from '~/types'
import { apiErrorMessage } from '~/lib/apiError'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { fixedQuestionTypes } from '~/lib/fixedQuestionTypes'
import ClearableSelect from './ClearableSelect.vue'
import RichContent from './rich-editor/RichContent.vue'
import { toast } from 'vue-sonner'

const props = defineProps<{ open: boolean; paper: ExamPaper; item: ExamPaperItem | null }>()
const emit = defineEmits<{ 'update:open': [value: boolean]; updated: [paper: ExamPaper] }>()
const { $api } = useNuxtApp()
type Candidate = { id: number; content: RichDoc; tags: { id: number; name: string }[]; warnings: string[] }
const keyword = ref('')
const typeId = ref<string | undefined>()
const condition = ref({tag_ids:[] as number[],match:'any' as 'any' | 'all'})
const override = ref(false)
const clearScope = ref(false)
const typeOptions = fixedQuestionTypes
const rows = ref<Candidate[]>([])
const page = ref(1)
const total = ref(0)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
let sequence = 0

async function search() {
  const token = ++sequence
  if (!props.open || !props.item) return
  loading.value = true
  error.value = ''
  try {
    const data = await $api<{ items: Candidate[]; total: number }>(`/exam-papers/${props.paper.id}/items/${props.item.id}/candidates`, {
      query: { keyword: keyword.value || undefined, q_type: typeId.value || undefined,
        tag_ids: condition.value.tag_ids, tag_match: condition.value.match, tag_filter_override:override.value, scope_override:clearScope.value, page: page.value, size: 20 },
    })
    // 筛选、翻页及关闭弹窗都会更新序号，旧响应不得覆盖当前候选列表。
    if (token === sequence) { rows.value = data.items; total.value = data.total }
  } catch (e) { if (token === sequence) { rows.value = []; error.value = apiErrorMessage(e, '候选题加载失败') } }
  finally { if (token === sequence) loading.value = false }
}

watch(() => props.open, async open => {
  if (!open) { ++sequence; return }
  keyword.value = ''
  typeId.value = props.item?.q_type
  const snap = props.paper.template_snapshot_json as any
  const rule = snap.parts?.flatMap((p:any) => p.sections).find((s:any) => s.key === props.item?.section_key)
  condition.value = JSON.parse(JSON.stringify(rule?.tag_filter ?? {tag_ids:[],match:'any'}))
  override.value = false; clearScope.value = false
  page.value = 1; rows.value = []
  await search()
})
watch([keyword, typeId, condition, clearScope], () => { page.value = 1; search() }, { deep: true })
watch(page, () => search())

async function choose(candidate: Candidate) {
  if (!props.item || saving.value) return
  if (candidate.warnings.length && !confirm(`此替换将偏离模板：\n${candidate.warnings.join('\n')}\n仍然替换？`)) return
  saving.value = true
  try {
    // 预览提示经用户确认后随请求显式提交，服务端仍会重新校验本次替换的偏离。
    const updated = await $api<ExamPaper>(`/exam-papers/${props.paper.id}/items/${props.item.id}/replace`, {
      method: 'POST', body: { mode: 'manual', question_id: candidate.id, accept_template_deviation: candidate.warnings.length > 0 },
    })
    emit('updated', updated)
    emit('update:open', false)
    toast.success('已替换，保留原题位分值')
  } catch (e) { toast.error(apiErrorMessage(e, '换题失败')); await search() }
  finally { saving.value = false }
}
</script>
<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent class="sm:max-w-3xl max-h-[85vh] overflow-y-auto">
      <DialogHeader><DialogTitle>手动选题换题</DialogTitle><DialogDescription>默认筛选当前题型、原规则标签及全卷范围。可调整筛选；偏离模板时将提示确认。已排除本题及禁止重复的题目。</DialogDescription></DialogHeader>
      <Input v-model="keyword" placeholder="搜索题干" />
      <div class="grid grid-cols-2 gap-3"><ClearableSelect v-model="typeId" :options="typeOptions" placeholder="全部题型" />
        <TagCondition v-model="condition" :subject-id="paper.subject_id" @update:model-value="override = true" /></div>
      <label class="text-sm"><input v-model="clearScope" type="checkbox" /> 本次候选不限制全卷范围（选入后需确认偏离）</label>
      <div v-if="error" role="alert" class="text-sm text-destructive">{{ error }} <Button variant="ghost" @click="search">重试</Button></div>
      <div v-else-if="loading" role="status">正在加载候选题…</div>
      <div v-else-if="!rows.length" class="text-sm text-muted-foreground">暂无可替换题目，请调整筛选条件。</div>
      <div v-for="candidate in rows" v-else :key="candidate.id" class="space-y-2 rounded border p-3">
        <RichContent :content="candidate.content" />
        <div class="flex flex-wrap gap-2"><span v-for="tag in candidate.tags" :key="tag.id" class="rounded border px-2 text-xs">{{ tag.name }}</span></div>
        <p v-for="warning in candidate.warnings" :key="warning" class="text-xs text-amber-700">{{ warning }}</p>
        <Button size="sm" :disabled="saving" @click="choose(candidate)">替换为此题</Button>
      </div>
      <div class="flex items-center justify-between text-sm"><span>共 {{ total }} 道</span><div class="flex gap-2">
        <Button variant="outline" :disabled="page <= 1 || loading" @click="page--">上一页</Button>
        <Button variant="outline" :disabled="page * 20 >= total || loading" @click="page++">下一页</Button>
      </div></div>
    </DialogContent>
  </Dialog>
</template>
