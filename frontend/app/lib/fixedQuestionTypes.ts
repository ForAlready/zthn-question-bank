import type { QuestionType } from '~/types'
export const fixedQuestionTypes: Array<{ value: QuestionType; label: string }> = [
  { value: 'single_choice', label: '单选题' }, { value: 'multiple_choice', label: '多选题' },
  { value: 'true_false', label: '判断题' }, { value: 'fill_in_the_blank', label: '填空题' },
  { value: 'free_response', label: '问答题' },
]
