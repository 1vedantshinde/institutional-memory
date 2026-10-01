/**
 * Parse [Finding N] markers from an answer string.
 * Returns an array of { marker, index } for rendering inline chips.
 */
export interface MarkerSpan {
  text: string       // text before this marker
  marker: string     // e.g. "Finding 1"
  label: string      // e.g. "F1" (short badge)
  findingKey: string // normalized key for lookup, e.g. "Finding 1"
}

export interface ParsedAnswer {
  segments: Array<{ text: string; marker?: string; label?: string; findingKey?: string }>
}

const FINDING_RE = /\[Finding (\d+)\]/g

export function parseAnswerSegments(answer: string): ParsedAnswer['segments'] {
  const segments: ParsedAnswer['segments'] = []
  let lastIndex = 0
  let match: RegExpExecArray | null

  FINDING_RE.lastIndex = 0
  while ((match = FINDING_RE.exec(answer)) !== null) {
    const text = answer.slice(lastIndex, match.index)
    if (text) segments.push({ text })
    const n = match[1]
    segments.push({
      text: '',
      marker: `Finding ${n}`,
      label: `F${n}`,
      findingKey: `Finding ${n}`,
    })
    lastIndex = FINDING_RE.lastIndex
  }
  const tail = answer.slice(lastIndex)
  if (tail) segments.push({ text: tail })
  return segments
}

/** Build a lookup map from label string ("Finding 1") to citation index */
export function buildCitationMap(citations: Array<{ label: string }>): Map<string, number> {
  const map = new Map<string, number>()
  citations.forEach((c, i) => map.set(c.label, i))
  return map
}
