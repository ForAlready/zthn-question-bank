<script setup lang="ts">
import { ArrowLeft } from '@lucide/vue'

defineProps<{
  title: string
}>()

const router = useRouter()
</script>

<template>
  <header class="flex h-14 shrink-0 items-center gap-2 border-b bg-card px-4 md:px-8">
    <Breadcrumb>
          <BreadcrumbList>
            <BreadcrumbItem>
              <BreadcrumbPage class="text-base font-semibold text-foreground">{{ title }}</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>
    <div class="ml-auto flex items-center gap-2">
      <slot name="actions" />
    </div>
  </header>
</template>