/** 组卷模板 / 考试试卷 — 对应后端 paper_template & exam_paper schemas */

import type { QuestionType } from './index'
export interface TagFilter { tag_ids: number[]; match: 'any' | 'all' }
export interface TemplateSection { key: string; q_type: QuestionType; tag_filter: TagFilter; count: number; score_each: number }
export interface TemplatePart { key: string; title: string; part_score: number; sections: TemplateSection[] }

export interface PaperTemplate {
  id: number
  subject_id: number
  name: string
  total_score: number
  parts: TemplatePart[]
  scope?: TagFilter
  duration_minutes?: number | null
  instructions?: string | null
  is_system_default: boolean
  enabled: boolean
  seed_key?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface PaperTemplateCreate {
  subject_id: number
  name: string
  total_score: number
  parts: TemplatePart[]
  scope?: TagFilter
  duration_minutes?: number | null
  instructions?: string | null
  enabled?: boolean
}

export interface PaperTemplateUpdate {
  name?: string
  total_score?: number
  parts?: TemplatePart[]
  scope?: TagFilter
  duration_minutes?: number | null
  instructions?: string | null
  enabled?: boolean
}

/** 一键出卷；n_sets>1 时生成平行卷，默认批次内去重。 */
export interface ExamPaperGenerateRequest {
  template_id: number
  title?: string | null
  n_sets?: number
  cross_set_dedup?: boolean
  scope?: TagFilter
  duration_minutes?: number | null
  seed?: string | null
}

export interface ExamPaperItem {
  id: number
  paper_id: number
  question_id: number
  part_key: string
  section_key: string
  q_type: QuestionType
  tag_snapshot_json: Array<{ id: number; name: string; group_id?: number | null }>
  seq: number
  score: number
  content_snapshot_json: {
    content?: unknown
    options?: Array<{ id?: string; label?: string; content?: unknown }> | null
    answer?: unknown
    analysis?: unknown
    thinking?: unknown
    summary?: unknown
    q_type?: string
  }
}

export type ExamPaperStatus = 'draft' | 'final' | string

export interface ExamPaper {
  id: number
  batch_id: number
  subject_id: number
  title: string
  set_index: number
  status: ExamPaperStatus
  template_snapshot_json: Record<string, unknown>
  actual_total_score: number
  duration_minutes?: number | null
  instructions?: string | null
  seed?: string | null
  finalized_at?: string | null
  created_by: number
  created_at?: string | null
  updated_at?: string | null
  template_warnings?: string[]
  items: ExamPaperItem[]
}

export interface ExamPaperBatch {
  id: number
  subject_id: number
  template_id: number
  n_sets: number
  cross_set_dedup: boolean
  scope_json?: unknown
  template_snapshot_json: Record<string, unknown>
  seed?: string | null
  created_by: number
  created_at?: string | null
  papers: ExamPaper[]
}

export type ExamPaperExportMode = 'with_answers' | 'without_answers'
