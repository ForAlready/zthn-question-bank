<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import type {
  Question,
  KnowledgePoint,
  Subject,
  QuestionType,
  OptionSpec,
} from '@/types'
import {
  Dialog,
  DialogScrollContent,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Plus, Trash2, Save, Loader2, X } from '@lucide/vue'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from 'vue-sonner'
import AnswerEditor from './AnswerEditor.vue'
import AnswerDisplay from './AnswerDisplay.vue'
import RichEditor from './rich-editor/RichEditor.vue'
import RichContent from './rich-editor/RichContent.vue'
import {
  type QuestionDraft,
  type ImportDraft,
  buildQuestionPayload,
  buildQuestionPatch,
  isMetadataOnlyPatch,
  cloneImportDraft,
  createDefaultOptions,
  createEmptyDraft,
  dbQuestionToDraft,
  generateOptionId,
  isChoiceType,
  nextOptionLabel,
  pruneAnswerOptionRef,
  validateQuestionDraft,
} from '@/lib/questionModel'

interface Props {
  open: boolean
  question?: ImportDraft | Question | Partial<Question> | null
  knowledgePoints?: KnowledgePoint[]
  subjects?: Subject[]
  mode?: 'import' | 'create' | 'edit'
  autoFillSubjectId?: number | null
}

const props = withDefaults(defineProps<Props>(), {
  mode: 'create',
  autoFillSubjectId: null,
})

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
  (e: 'success', data: Question): void
  (e: 'save', question: ImportDraft): void
}>()

const { $api } = useNuxtApp()

const isImportMode = computed(() => props.mode === 'import')

// 所有模式统一走 v2 RichDoc 草稿；import 模式只是不落库，保存时把草稿回抛给评审列表。
const draft = ref<QuestionDraft | null>(null)
const initialDraft = ref<QuestionDraft | null>(null)
// import 模式下随草稿一起回抛的列表态（列表 key / 选中 / 警告 / AI 建议标签）。
const importMeta = ref<Pick<ImportDraft, 'uid' | 'selected' | 'warnings' | 'ai_suggested_tags' | 'raw_type_name' | 'raw_answer'> | null>(null)
const suggestedLabels = computed(() => [...new Set(Object.values(importMeta.value?.ai_suggested_tags ?? {}).flat())])

const isSubmitting = ref(false)

const activeSubjectId = computed<number | undefined>(
  () =>
    draft.value?.subject_id
    ?? props.autoFillSubjectId
    ?? undefined,
)

// --- shared field accessors (draft is the single edit state for all modes) ---
const qType = computed<QuestionType | undefined>({
  get: () => draft.value?.q_type ?? undefined,
  set: (v) => {
    if (draft.value && v) switchDraftType(draft.value, v)
  },
})

const difficulty = computed<number>({
  get: () => draft.value?.difficulty ?? 3,
  set: (v) => {
    if (draft.value) draft.value.difficulty = v
  },
})

const parentId = computed<number | undefined>({
  get: () => draft.value?.parent_id ?? undefined,
  set: (v) => {
    if (draft.value) draft.value.parent_id = v == null || Number.isNaN(v) ? null : Number(v)
  },
})

// --- db draft type switching: reinit options + answer for the new variant ---
function switchDraftType(d: QuestionDraft, newType: QuestionType) {
  const oldType = d.q_type
  if (oldType === newType) return
  if (d.answer && !window.confirm('更改题型需要重新填写答案，是否继续？')) return
  d.q_type = newType
  if (isChoiceType(newType) && d.options.length === 0) {
    d.options = createDefaultOptions()
  }
  d.answer = null
}

const initState = () => {
  if (isImportMode.value) {
    const fallbackSubject = props.autoFillSubjectId ?? undefined
    const src = props.question as ImportDraft | null
    const item = src ? cloneImportDraft(src) : { ...createEmptyDraft({ subjectId: fallbackSubject }), uid: 'temp-' + Date.now(), selected: true, warnings: [] } as ImportDraft
    if (!item.subject_id && fallbackSubject) item.subject_id = fallbackSubject
    importMeta.value = {
      uid: item.uid,
      selected: item.selected,
      warnings: item.warnings,
      raw_type_name: item.raw_type_name,
      raw_answer: item.raw_answer,
      ai_suggested_tags: item.ai_suggested_tags,
    }
    draft.value = item
  } else {
    importMeta.value = null
    const fallbackSubject =
      props.autoFillSubjectId
      ?? (props.subjects && props.subjects.length === 1 ? props.subjects[0]?.id : undefined)
      ?? undefined
    draft.value = dbQuestionToDraft(
      (props.question as Partial<Question>) ?? {},
      { subjectId: fallbackSubject },
    )
  }
}

// 留存独立的初始快照用于生成差量请求，避免将未编辑的历史内容一并提交。
const initialize = () => { initState(); initialDraft.value = draft.value ? JSON.parse(JSON.stringify(draft.value)) : null }
watch(() => props.question, initialize, { immediate: true })
watch(() => props.open, (isOpen) => { if (isOpen) { initialize() } })
watch(() => props.mode, initialize)

const title = computed(() => (props.mode === 'edit' ? '编辑题目' : '新增题目'))

// --- db draft option handlers (v2 OptionSpec with stable ids) ---
const draftAddOption = () => {
  if (!draft.value) return
  const opt: OptionSpec = {
    id: generateOptionId(),
    label: nextOptionLabel(draft.value.options.length),
    content: null,
  }
  draft.value.options.push(opt)
}
const draftRemoveOption = (index: number) => {
  if (!draft.value) return
  const [removed] = draft.value.options.splice(index, 1)
  // 重排 label（A/B/C…）并清理 answer 对被删选项的引用。
  draft.value.options.forEach((o, i) => { o.label = nextOptionLabel(i) })
  if (removed) draft.value.answer = pruneAnswerOptionRef(draft.value.answer, removed.id)
}

// --- save flows ---
// 导入评审保存不做硬校验：最终「确认导入」时再统一校验/降级，允许中途保存不完整草稿。
const handleSaveImport = () => {
  if (!draft.value || !importMeta.value) return
  if (!draft.value.q_type) { toast.error("请选择题型"); return }
  emit('save', { ...(draft.value as ImportDraft), ...importMeta.value })
  emit('update:open', false)
}

const handlePublish = async () => {
  if (!draft.value) return
  const patch = props.mode === 'edit' && initialDraft.value ? buildQuestionPatch(draft.value, initialDraft.value) : null
  // 标签等元数据变更不要求修复历史答案；与后端的元数据更新路径保持一致。
  const error = patch && isMetadataOnlyPatch(patch) ? null : validateQuestionDraft(draft.value)
  if (error) {
    toast.error(error)
    return
  }
  isSubmitting.value = true
  try {
    const payload = patch ?? buildQuestionPayload(draft.value)
    let saved: Question
    if (props.mode === 'edit' && draft.value.id) {
      saved = await $api<Question>(`/questions/${draft.value.id}`, { method: 'PUT', body: payload })
    } else {
      saved = await $api<Question>('/questions', { method: 'POST', body: payload })
    }
    emit('success', saved)
    emit('update:open', false)
  } catch (err: unknown) {
    console.error(err)
    toast.error('保存失败', { description: err instanceof Error ? err.message : undefined })
  } finally {
    isSubmitting.value = false
  }
}

const handleClose = () => emit('update:open', false)

// MathLive 虚拟键盘渲染在弹窗之外，点击它会触发 Dialog 的“点击外部关闭”；目标在键盘内时阻止关闭。
const onInteractOutside = (event: Event) => {
  const detail = (event as CustomEvent).detail as { originalEvent?: Event } | undefined
  const target = (detail?.originalEvent?.target ?? event.target) as HTMLElement | null
  if (target?.closest?.('[class*="ML__keyboard"], [class*="MLK__"], [class*="ML__virtual-keyboard"]')) {
    event.preventDefault()
  }
}

</script>

<template>
  <Dialog :open="open" @update:open="handleClose">
    <DialogScrollContent
      :show-close-button="false"
      class="bg-background !my-0 !max-w-none !min-w-full !p-0 !rounded-none !border-none !shadow-none !min-h-screen lg:!h-screen lg:overflow-hidden"
      @interact-outside="onInteractOutside"
    >
      <div class="flex w-full flex-col bg-background min-h-screen lg:h-full">
        <!-- Header -->
        <div class="sticky top-0 z-50 flex items-center justify-between border-b border-border/50 px-6 py-4 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80 lg:static lg:bg-background">
          <DialogTitle class="text-lg">{{ isImportMode ? '编辑导入题目' : title }}</DialogTitle>
          <div class="flex items-center gap-2">
            <Button v-if="!isImportMode" size="sm" @click="handlePublish" :disabled="isSubmitting">
              <Loader2 v-if="isSubmitting" class="mr-2 h-4 w-4 animate-spin" />
              <Save v-else class="mr-2 h-4 w-4" />
              {{ mode === 'create' ? '保存' : '更新' }}
            </Button>
            <Button v-else size="sm" @click="handleSaveImport">
              <Save class="mr-2 h-4 w-4" />
              保存
            </Button>
            <Button variant="outline" size="sm" @click="handleClose">关闭</Button>
          </div>
        </div>

        <!-- Content -->
        <div class="flex-1 lg:min-h-0">
          <div class="grid gap-0 lg:grid-cols-[minmax(0,60%)_minmax(0,40%)] lg:h-full">
            <!-- Editor (Left) -->
            <section class="border-b border-border/50 bg-background px-6 py-6 lg:border-b-0 lg:border-r lg:h-full lg:overflow-y-auto">
              <div class="mx-auto max-w-3xl space-y-6">

                <!-- Type & Difficulty (+ db-only status/parent) -->
                <div class="grid grid-cols-2 gap-4">
                  <div class="space-y-2">
                    <Label>题型</Label>
                    <Select v-model="qType">
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="single_choice">单选题</SelectItem>
                        <SelectItem value="multiple_choice">多选题</SelectItem>
                        <SelectItem value="true_false">判断题</SelectItem>
                        <SelectItem value="fill_in_the_blank">填空题</SelectItem>
                        <SelectItem value="free_response">问答题</SelectItem>
                      </SelectContent>
                    </Select>
                    <p class="text-xs text-muted-foreground">简答、论述、案例分析统一使用问答题。</p>
                    <p v-if="isImportMode && importMeta?.raw_type_name" class="text-xs text-muted-foreground">原题型：{{ importMeta.raw_type_name }}</p>
                    <p v-if="isImportMode && importMeta?.raw_answer" class="text-xs text-amber-700">原答案（请复核填写）：{{ importMeta.raw_answer }}</p>
                  </div>
                  <div v-if="!isImportMode && draft" class="space-y-2">
                    <Label>状态</Label>
                    <Select v-model="draft.status">
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="draft">草稿</SelectItem>
                        <SelectItem value="pending">待审核</SelectItem>
                        <SelectItem value="published">已发布</SelectItem>
                        <SelectItem value="archived">已归档</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div class="space-y-2">
                    <Label>难度</Label>
                    <Select v-model.number="difficulty">
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem :value="1">难度 1</SelectItem>
                        <SelectItem :value="2">难度 2</SelectItem>
                        <SelectItem :value="3">难度 3</SelectItem>
                        <SelectItem :value="4">难度 4</SelectItem>
                        <SelectItem :value="5">难度 5</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div v-if="!isImportMode && draft" class="space-y-2">
                    <Label>父题目 ID (可选)</Label>
                    <Input v-model.number="parentId" type="number" placeholder="输入原题 ID" />
                  </div>
                </div>

                <!-- Source (db only) -->
                <div v-if="!isImportMode && draft" class="space-y-2">
                  <Label>来源</Label>
                  <Input v-model="draft.source" placeholder="输入题目来源" />
                </div>

                <!-- Visibility (db only) -->
                <div v-if="!isImportMode && draft" class="space-y-2">
                  <Label>可见性</Label>
                  <Select v-model="draft.visibility">
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="public">公开（学科内共享）</SelectItem>
                      <SelectItem value="private">私有（仅自己可见）</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <!-- Categories -->
                <div v-if="draft" class="space-y-2">
                  <Label>标签</Label>
                  <FlatTagSelect v-if="draft" v-model="draft.tag_ids" :subject-id="activeSubjectId" />
                  <p v-if="isImportMode && suggestedLabels.length" class="text-xs text-muted-foreground">提取的标签建议：{{ suggestedLabels.join('、') }}。未匹配的建议请人工确认。</p>
                </div>

                <!-- ================= v2 editors (all modes) ================= -->
                <template v-if="draft">
                  <div class="space-y-2">
                    <Label>题干</Label>
                    <RichEditor v-model="draft.content" :allow-blank="qType === 'fill_in_the_blank'" />
                  </div>

                  <div v-if="qType === 'single_choice' || qType === 'multiple_choice'" class="space-y-2">
                    <Label>选项</Label>
                    <div class="grid grid-cols-1 gap-4">
                      <div v-for="(opt, optIndex) in draft.options" :key="opt.id" class="flex gap-2 items-start">
                        <div class="w-8 h-9 flex items-center justify-center bg-muted rounded font-medium shrink-0 mt-0.5">{{ opt.label }}</div>
                        <div class="flex-1">
                          <RichEditor v-model="opt.content" placeholder="输入选项内容…" />
                        </div>
                        <Button variant="ghost" size="icon" class="h-8 w-8 mt-0.5" @click="draftRemoveOption(optIndex)">
                          <Trash2 class="h-3 w-3" />
                        </Button>
                      </div>
                      <Button variant="outline" class="w-full border-dashed" @click="draftAddOption">
                        <Plus class="h-4 w-4 mr-2" /> 添加选项
                      </Button>
                    </div>
                  </div>

                  <AnswerEditor
                    v-model="draft.answer"
                    :q-type="draft.q_type || 'single_choice'"
                    :options="draft.options"
                    :stem="draft.content"
                  />

                  <div class="space-y-2">
                    <Label>分析</Label>
                    <RichEditor v-model="draft.thinking" />
                  </div>
                  <div class="space-y-2">
                    <Label>解析</Label>
                    <RichEditor v-model="draft.analysis" />
                  </div>
                  <div class="space-y-2">
                    <Label>总结</Label>
                    <RichEditor v-model="draft.summary" />
                  </div>
                </template>
              </div>
            </section>

            <!-- Preview (Right) -->
            <aside class="border-t border-border/50 bg-muted/20 px-6 py-6 lg:border-t-0 lg:border-l lg:h-full lg:overflow-y-auto">
              <div class="mx-auto max-w-3xl space-y-6">

                <!-- v2 preview: RichContent (all modes) -->
                <template v-if="draft">
                  <div class="space-y-2">
                    <h3 class="font-semibold text-sm text-muted-foreground">题目预览</h3>
                    <div class="bg-background p-4 rounded border border-border">
                      <RichContent :content="draft.content" empty-text="（空）" />
                    </div>
                  </div>
                  <div v-if="(qType === 'single_choice' || qType === 'multiple_choice') && draft.options.length > 0" class="space-y-2">
                    <h3 class="font-semibold text-sm text-muted-foreground">选项预览</h3>
                    <div class="space-y-2 bg-background p-4 rounded border border-border">
                      <div v-for="opt in draft.options" :key="opt.id" class="flex gap-2">
                        <span class="font-bold text-muted-foreground shrink-0">{{ opt.label }}.</span>
                        <div class="flex-1 [&_.prose]:my-0 [&_.prose>p]:my-0">
                          <RichContent :content="opt.content" empty-text="（空选项）" />
                        </div>
                      </div>
                    </div>
                  </div>
                  <div class="space-y-2">
                    <h3 class="font-semibold text-sm text-muted-foreground">答案</h3>
                    <div class="bg-background p-4 rounded border border-border">
                      <AnswerDisplay :answer="draft.answer" :options="draft.options" empty-text="（未填写）" />
                    </div>
                  </div>
                  <div v-if="draft.thinking" class="space-y-2">
                    <h3 class="font-semibold text-sm text-muted-foreground">分析</h3>
                    <div class="bg-background p-4 rounded border border-border">
                      <RichContent :content="draft.thinking" />
                    </div>
                  </div>
                  <div v-if="draft.analysis" class="space-y-2">
                    <h3 class="font-semibold text-sm text-muted-foreground">解析</h3>
                    <div class="bg-background p-4 rounded border border-border">
                      <RichContent :content="draft.analysis" />
                    </div>
                  </div>
                  <div v-if="draft.summary" class="space-y-2">
                    <h3 class="font-semibold text-sm text-muted-foreground">总结</h3>
                    <div class="bg-background p-4 rounded border border-border">
                      <RichContent :content="draft.summary" />
                    </div>
                  </div>
                </template>
              </div>
            </aside>
          </div>
        </div>
      </div>
    </DialogScrollContent>
  </Dialog>
</template>
