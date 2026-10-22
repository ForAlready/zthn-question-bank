<script setup lang="ts">
import type { TagFilter } from '~/types/paper'
const props = defineProps<{ modelValue: TagFilter; subjectId?: number | null; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [TagFilter] }>()
</script>
<template>
  <div class="space-y-2">
    <select aria-label="标签匹配方式" class="h-9 rounded-md border bg-background px-2 text-sm" :disabled="disabled"
      :value="modelValue.match" @change="emit('update:modelValue', { ...modelValue, match: ($event.target as HTMLSelectElement).value as 'any' | 'all' })">
      <option value="any">命中任一标签</option><option value="all">同时包含全部标签</option>
    </select>
    <FlatTagSelect :model-value="modelValue.tag_ids" :subject-id="subjectId" :disabled="disabled"
      @update:model-value="emit('update:modelValue', { ...modelValue, tag_ids: $event })" />
    <p class="text-xs text-muted-foreground">{{ !modelValue.tag_ids.length ? '不限制标签' : modelValue.match === 'all' ? '题目须同时包含以上全部标签' : '题目命中以上任一标签即可' }}</p>
  </div>
</template>
