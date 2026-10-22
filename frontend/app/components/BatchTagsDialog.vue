<script setup lang="ts">
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
const props = defineProps<{ open: boolean; subjectId?: number | null; count: number; busy?: boolean }>()
const emit = defineEmits<{ 'update:open': [boolean]; submit: [{ operation: string; tag_ids: number[] }] }>()
const operation = ref('append')
const ids = ref<number[]>([])
watch(() => props.open, value => { if (value) { operation.value = 'append'; ids.value = [] } })
</script>
<template>
  <Dialog :open="open" @update:open="emit('update:open', $event)">
    <DialogContent><DialogHeader><DialogTitle>批量维护标签</DialogTitle><DialogDescription>对选中的 {{ count }} 道题执行标签操作。</DialogDescription></DialogHeader>
      <select v-model="operation" aria-label="批量操作" class="h-9 rounded border bg-background px-2">
        <option value="append">追加标签</option><option value="replace">替换标签</option><option value="remove">移除标签</option><option value="clear">清空标签</option>
      </select>
      <FlatTagSelect v-if="operation !== 'clear'" v-model="ids" :subject-id="subjectId" />
      <p v-else>将移除这些题目的全部标签。</p>
      <Button :disabled="busy" @click="emit('submit', { operation, tag_ids: operation === 'clear' ? [] : ids })">{{ busy ? '正在保存…' : '确认修改' }}</Button>
    </DialogContent>
  </Dialog>
</template>
