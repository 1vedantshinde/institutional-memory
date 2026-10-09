import { describe, it, expect } from 'vitest'
import { parseAnswerSegments } from './citations'

const markers = (text: string) => parseAnswerSegments(text).filter((s) => s.marker).map((s) => s.marker)

describe('parseAnswerSegments', () => {
  it('finds single finding and source markers', () => {
    expect(markers('A [Finding 1] and B [Source 2].')).toEqual(['Finding 1', 'Source 2'])
  })

  it('splits grouped markers the model sometimes writes', () => {
    expect(markers('RMS is strength [Source 1, Source 3].')).toEqual(['Source 1', 'Source 3'])
    expect(markers('Windows rose [Finding 1, 2].')).toEqual(['Finding 1', 'Finding 2'])
    expect(markers('Mixed [Finding 1; Source 2].')).toEqual(['Finding 1', 'Source 2'])
  })

  it('leaves other bracketed text alone', () => {
    expect(markers('Range [0, 2048] and [Note 1].')).toEqual([])
    expect(parseAnswerSegments('plain text')).toEqual([{ text: 'plain text' }])
  })
})
