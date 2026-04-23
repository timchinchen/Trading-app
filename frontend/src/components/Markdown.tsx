/**
 * Lightweight markdown renderer — no external dependencies.
 * Handles the subset the LLM actually produces:
 *   - **bold**, *italic*, `inline code`
 *   - Numbered lists (1. 2. 3.)
 *   - Bullet lists (- or *)
 *   - Horizontal rules (--- / ***)
 *   - Blank-line paragraph breaks
 */
import React from 'react'

// ---------------------------------------------------------------------------
// Inline renderer: bold, italic, inline code
// ---------------------------------------------------------------------------
function renderInline(text: string): React.ReactNode[] {
  // Split on **bold**, *italic*, `code` — in that priority order.
  const pattern = /(\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`)/g
  const nodes: React.ReactNode[] = []
  let last = 0
  let match: RegExpExecArray | null

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index))
    if (match[0].startsWith('**')) {
      nodes.push(<strong key={match.index}>{match[2]}</strong>)
    } else if (match[0].startsWith('*')) {
      nodes.push(<em key={match.index}>{match[3]}</em>)
    } else {
      nodes.push(
        <code
          key={match.index}
          className="bg-muted/60 rounded px-1 py-0.5 text-[0.85em] font-mono"
        >
          {match[4]}
        </code>,
      )
    }
    last = match.index + match[0].length
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

// ---------------------------------------------------------------------------
// Block-level tokeniser
// ---------------------------------------------------------------------------
type Block =
  | { type: 'paragraph'; text: string }
  | { type: 'bullet'; items: string[] }
  | { type: 'ordered'; items: string[] }
  | { type: 'hr' }

function tokenise(raw: string): Block[] {
  const lines = raw.split('\n')
  const blocks: Block[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    // Blank line — skip
    if (line.trim() === '') { i++; continue }

    // Horizontal rule
    if (/^(-{3,}|\*{3,})$/.test(line.trim())) {
      blocks.push({ type: 'hr' })
      i++
      continue
    }

    // Ordered list item
    if (/^\d+\.\s/.test(line)) {
      const items: string[] = []
      while (i < lines.length && /^\d+\.\s/.test(lines[i])) {
        items.push(lines[i].replace(/^\d+\.\s*/, ''))
        i++
      }
      blocks.push({ type: 'ordered', items })
      continue
    }

    // Bullet list item
    if (/^[-*]\s/.test(line)) {
      const items: string[] = []
      while (i < lines.length && /^[-*]\s/.test(lines[i])) {
        items.push(lines[i].replace(/^[-*]\s*/, ''))
        i++
      }
      blocks.push({ type: 'bullet', items })
      continue
    }

    // Paragraph — collect consecutive non-special lines
    const paragraphLines: string[] = []
    while (
      i < lines.length &&
      lines[i].trim() !== '' &&
      !/^(\d+\.|[-*])\s/.test(lines[i]) &&
      !/^(-{3,}|\*{3,})$/.test(lines[i].trim())
    ) {
      paragraphLines.push(lines[i])
      i++
    }
    if (paragraphLines.length) {
      blocks.push({ type: 'paragraph', text: paragraphLines.join(' ') })
    }
  }

  return blocks
}

// ---------------------------------------------------------------------------
// Public component
// ---------------------------------------------------------------------------
export function Markdown({ children }: { children: string }) {
  const blocks = tokenise(children)

  return (
    <div className="space-y-2 text-sm leading-relaxed">
      {blocks.map((block, idx) => {
        if (block.type === 'hr') {
          return <hr key={idx} className="border-border my-2" />
        }
        if (block.type === 'paragraph') {
          return <p key={idx}>{renderInline(block.text)}</p>
        }
        if (block.type === 'ordered') {
          return (
            <ol key={idx} className="list-decimal list-outside ml-5 space-y-1">
              {block.items.map((item, j) => (
                <li key={j}>{renderInline(item)}</li>
              ))}
            </ol>
          )
        }
        if (block.type === 'bullet') {
          return (
            <ul key={idx} className="list-disc list-outside ml-5 space-y-1">
              {block.items.map((item, j) => (
                <li key={j}>{renderInline(item)}</li>
              ))}
            </ul>
          )
        }
        return null
      })}
    </div>
  )
}
