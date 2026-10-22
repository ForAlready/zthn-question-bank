<script setup lang="ts">
import type { Tag, TagPage } from '~/types'
const props = defineProps<{ modelValue: number[]; subjectId?: number | null; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [number[]] }>()
const { $api } = useNuxtApp()
const tags = ref<Tag[]>([])
const keyword = ref('')
const error = ref('')
const loading = ref(false)
let sequence = 0
async function load() {
  const token = ++sequence
  tags.value = []
  if (!props.subjectId) return
  loading.value = true
  error.value = ''
  try {
    const result = await $api<TagPage>('/tags', { query: { subject_id: props.subjectId, size: -1 } })
    if (token === sequence) tags.value = result.items
  } catch { if (token === sequence) error.value = '标签加载失败，请重试' }
  finally { if (token === sequence) loading.value = false }
}
watch(() => props.subjectId, load, { immediate: true })
const visible = computed(() => tags.value.filter(t => t.name.includes(keyword.value)))
function toggle(tag: Tag) {
  const ids = new Set(props.modelValue)
  if (ids.has(tag.id)) ids.delete(tag.id)
  else if (tag.enabled !== false) ids.add(tag.id)
  emit('update:modelValue', [...ids])
}
</script>

<template>
  <div class="space-y-2">
    <div class="flex flex-wrap gap-1">
      <button v-for="id in modelValue" :key="id" type="button" :disabled="disabled"
        class="rounded border bg-primary/5 px-2 py-1 text-xs" @click="emit('update:modelValue', modelValue.filter(v => v !== id))">
        {{ tags.find(t => t.id === id)?.name ?? `标签 #${id}` }}
        {{ tags.find(t => t.id === id)?.enabled === false ? '（已停用）' : '' }} ×
      </button>
    </div>
    <input v-model="keyword" aria-label="搜索标签" placeholder="搜索并多选标签" :disabled="disabled"
      class="h-9 w-full rounded-md border bg-background px-3 text-sm" />
    <p v-if="loading" class="text-xs text-muted-foreground">正在加载标签…</p>
    <button v-else-if="error" type="button" class="text-sm text-destructive" @click="load">{{ error }}</button>
    <div v-else class="flex max-h-32 flex-wrap gap-1 overflow-auto">
      <button v-for="tag in visible" :key="tag.id" type="button" :aria-pressed="modelValue.includes(tag.id)"
        :disabled="disabled || (tag.enabled === false && !modelValue.includes(tag.id))"
        class="rounded border px-2 py-1 text-xs disabled:opacity-50"
        :class="modelValue.includes(tag.id) ? 'border-primary bg-primary/10 text-primary' : 'bg-background'"
        @click="toggle(tag)">{{ tag.name }}{{ tag.enabled === false ? '（已停用）' : '' }}</button>
      <span v-if="!visible.length" class="text-xs text-muted-foreground">没有可选标签</span>
    </div>
  </div>
</template>
