import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { TooltipProvider } from '@/components/ui/tooltip'
import { AnswerRenderer } from './AnswerRenderer'
import { MOCK_CHAT_DOCUMENTS_ANSWER as DOC } from '@/mocks/fixtures'
import { ChatReadyResponseSchema } from '@/api/schemas'

function renderDocAnswer() {
  return render(
    <TooltipProvider>
      <AnswerRenderer answer={DOC.answer} citations={[]} sources={DOC.sources} findingCount={0} onCitationClick={() => {}} />
    </TooltipProvider>,
  )
}

describe('AnswerRenderer — knowledge-document answers', () => {
  it('accepts the documents response shape', () => {
    expect(ChatReadyResponseSchema.parse(DOC).sources).toHaveLength(2)
  })

  it('turns [Source N] markers into chips and labels the answer as document-based', () => {
    renderDocAnswer()
    expect(screen.getAllByRole('button', { name: /show passage for source 1 from glossary\.pdf/i })).toHaveLength(2)
    expect(screen.getByText('Answered from project documents')).toBeInTheDocument()
    expect(screen.queryByText(/grounded by 0 findings/i)).not.toBeInTheDocument()
    expect(screen.queryByText('[Source 1]')).not.toBeInTheDocument()
  })

  it('opens and closes the cited passage', () => {
    renderDocAnswer()
    fireEvent.click(screen.getByRole('button', { name: /show passage: source 2, finding_explainer\.pdf/i }))
    expect(screen.getByRole('region', { name: /passage for source 2/i })).toHaveTextContent('2,048 consecutive readings')
    fireEvent.click(screen.getByRole('button', { name: /close passage/i }))
    expect(screen.queryByRole('region', { name: /passage for source 2/i })).not.toBeInTheDocument()
  })
})
