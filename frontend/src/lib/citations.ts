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

// [Finding N] cites a computed finding; [Source N] a knowledge-document passage.
// Models sometimes group them — "[Source 1, Source 3]" or "[Finding 1, 2]" —
// so a bracket may hold several, each becoming its own chip.
const MARKER_RE = /\[((?:Finding|Source) \d+(?:\s*[,;&]\s*(?:(?:and\s+)?(?:Finding|Source)\s+)?\d+)*)\]/g
const ITEM_RE = /(?:(Finding|Source)\s+)?(\d+)/g

export function parseAnswerSegments(answer: string): ParsedAnswer['segments'] {
  const segments: ParsedAnswer['segments'] = []
  let lastIndex = 0
  let match: RegExpExecArray | null

  MARKER_RE.lastIndex = 0
  while ((match = MARKER_RE.exec(answer)) !== null) {
    const text = answer.slice(lastIndex, match.index)
    if (text) segments.push({ text })
    let kind = 'Finding'
    let item: RegExpExecArray | null
    ITEM_RE.lastIndex = 0
    while ((item = ITEM_RE.exec(match[1])) !== null) {
      kind = item[1] ?? kind // "[Finding 1, 2]" → both are findings
      const n = item[2]
      segments.push({
        text: '',
        marker: `${kind} ${n}`,
        label: `${kind === 'Source' ? 'S' : 'F'}${n}`,
        findingKey: `${kind} ${n}`,
      })
    }
    lastIndex = MARKER_RE.lastIndex
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
