import { describe, it, expect } from 'vitest'
import { parseAnswerBlocks, splitBold } from './answerBlocks'

// Shape of a real answer from the backend (condition 4, Vib_Spindle)
const REAL = `### Practical Summary
During condition 4, spindle vibration showed an anomaly
compared to the condition baseline.

### Representative Findings
* **[Finding 1]**: Low-frequency vibration energy was 2.99 standard deviations above baseline.
* **[Finding 2]**: Overall vibration level (RMS) was 3.05 standard deviations above baseline.`

describe('parseAnswerBlocks', () => {
  it('splits headings, paragraphs and bullet lists', () => {
    expect(parseAnswerBlocks(REAL)).toEqual([
      { type: 'heading', text: 'Practical Summary' },
      { type: 'paragraph', text: 'During condition 4, spindle vibration showed an anomaly compared to the condition baseline.' },
      { type: 'heading', text: 'Representative Findings' },
      { type: 'list', items: [
        '**[Finding 1]**: Low-frequency vibration energy was 2.99 standard deviations above baseline.',
        '**[Finding 2]**: Overall vibration level (RMS) was 3.05 standard deviations above baseline.',
      ] },
    ])
  })

  it('treats a bold-only line as a heading-free paragraph and plain text as one paragraph', () => {
    expect(parseAnswerBlocks('**Summary**  \nNo, not stable [Finding 1].')).toEqual([
      { type: 'paragraph', text: '**Summary** No, not stable [Finding 1].' },
    ])
  })

  it('keeps a plain one-line answer as a single paragraph', () => {
    expect(parseAnswerBlocks('Energy rose [Finding 1].')).toEqual([{ type: 'paragraph', text: 'Energy rose [Finding 1].' }])
  })
})

describe('splitBold', () => {
  it('alternates plain and bold runs', () => {
    expect(splitBold('**[Finding 1]**: text')).toEqual([
      { text: '[Finding 1]', bold: true },
      { text: ': text', bold: false },
    ])
  })

  it('leaves unbalanced markers as literal text', () => {
    expect(splitBold('a ** b')).toEqual([{ text: 'a ** b', bold: false }])
  })
})
