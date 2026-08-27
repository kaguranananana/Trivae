import { describe, expect, it } from 'vitest'
import { buildProcessSegments, formatProcessDuration, hasProcessSegmentError, isActiveProcessSegment } from '@/components/chat/processSegments'

interface Block {
  kind: string
  text?: string
  error?: boolean
}

const isFoldable = (block: Block) => block.kind !== 'text'
const isText = (block: Block) => block.kind === 'text'
const hasError = (block: Block) => block.error === true

describe('buildProcessSegments timeline mode', () => {
  it('groups consecutive process blocks and splits on text', () => {
    const blocks: Block[] = [
      { kind: 'route' },
      { kind: 'thinking' },
      { kind: 'tool' },
      { kind: 'text', text: '答案' },
    ]
    const segments = buildProcessSegments(blocks, { isFoldable, isText, mode: 'timeline' })
    expect(segments).toHaveLength(2)
    expect(segments[0]?.type).toBe('process')
    const processSegment = segments[0]
    if (processSegment?.type === 'process') expect(processSegment.blocks).toHaveLength(3)
    expect(segments[1]).toEqual({ type: 'visible', block: blocks[3] })
  })

  it('keeps process-only stream in one active group', () => {
    const blocks: Block[] = [{ kind: 'route' }, { kind: 'thinking' }]
    const segments = buildProcessSegments(blocks, { isFoldable, isText, mode: 'timeline' })
    expect(segments).toHaveLength(1)
    expect(isActiveProcessSegment(segments, 0, true)).toBe(true)
    expect(segments[0]).toBeDefined()
  })
})

describe('buildProcessSegments completed mode', () => {
  it('collapses all process blocks and intermediate text into one group, keeps final answer outside', () => {
    const blocks: Block[] = [
      { kind: 'route' },
      { kind: 'thinking' },
      { kind: 'text', text: '中间说明' },
      { kind: 'tool' },
      { kind: 'text', text: '最终答案' },
    ]
    const segments = buildProcessSegments(blocks, { isFoldable, isText, mode: 'completed' })
    const processSegments = segments.filter((segment) => segment.type === 'process')
    expect(processSegments).toHaveLength(1)
    const visible = segments.filter((segment) => segment.type === 'visible')
    expect(visible).toHaveLength(1)
    const lastSegment = segments[segments.length - 1]
    if (lastSegment?.type === 'visible') {
      expect(lastSegment.block.text).toBe('最终答案')
    } else {
      throw new Error('final answer should stay outside the process group')
    }
  })
})

describe('error segments', () => {
  it('detects error blocks for default expansion', () => {
    const segments = buildProcessSegments(
      [{ kind: 'tool', error: true }, { kind: 'text', text: '答案' }],
      { isFoldable, isText, mode: 'completed' },
    )
    expect(segments[0]).toBeDefined()
    expect(hasProcessSegmentError(segments[0], hasError)).toBe(true)
  })
})

describe('formatProcessDuration', () => {
  it('renders seconds and minutes', () => {
    expect(formatProcessDuration(3700)).toBe('4秒')
    expect(formatProcessDuration(125_000)).toBe('2分05秒')
  })
})
