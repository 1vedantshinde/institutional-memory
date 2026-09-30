/**
 * Splits an LLM answer into the small Markdown subset the backend produces
 * (headings, bullet lists, paragraphs, **bold**). Output is plain data that
 * AnswerRenderer turns into React elements — no HTML is ever interpreted.
 */

export type AnswerBlock =
  | { type: 'heading'; text: string }
  | { type: 'list'; items: string[] }
  | { type: 'paragraph'; text: string }

const HEADING_RE = /^\s{0,3}#{1,6}\s+(.*)$/
const BULLET_RE = /^\s*(?:[*\-•]|\d+[.)])\s+(.*)$/

export function parseAnswerBlocks(answer: string): AnswerBlock[] {
  const blocks: AnswerBlock[] = []
  let paragraph: string[] = []

  const flushParagraph = () => {
    if (paragraph.length) blocks.push({ type: 'paragraph', text: paragraph.join(' ') })
    paragraph = []
  }

  for (const line of answer.split(/\r?\n/)) {
    const heading = HEADING_RE.exec(line)
    const bullet = BULLET_RE.exec(line)
    if (!line.trim()) {
      flushParagraph()
    } else if (heading) {
      flushParagraph()
      blocks.push({ type: 'heading', text: heading[1].replace(/\*\*/g, '').trim() })
    } else if (bullet) {
      flushParagraph()
      const last = blocks[blocks.length - 1]
      if (last?.type === 'list') last.items.push(bullet[1])
      else blocks.push({ type: 'list', items: [bullet[1]] })
    } else {
      paragraph.push(line.trim())
    }
  }
  flushParagraph()
  return blocks
}

/**
 * Splits text on `**` into alternating plain/bold runs. Unbalanced markers
 * are left as literal text rather than bolding the rest of the line.
 */
export function splitBold(text: string): Array<{ text: string; bold: boolean }> {
  const parts = text.split('**')
  if (parts.length % 2 === 0) return [{ text, bold: false }]
  return parts.map((t, i) => ({ text: t, bold: i % 2 === 1 })).filter((p) => p.text)
}
