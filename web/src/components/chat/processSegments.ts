/**
 * Process 分段逻辑（继承 ChatLab chatMessageProcessSegments.ts）：
 * - timeline（运行中）：连续的 process 块成组，文本块（最终回答）切段；
 * - completed（完成后）：所有 process 块与中间文本合并为单个组，最终回答保持在组外。
 */

export type ProcessSegment<T> = { type: 'process'; blocks: T[] } | { type: 'visible'; block: T }

export interface ProcessSegmentOptions<T> {
  isFoldable: (block: T) => boolean
  isText: (block: T) => boolean
  mode: 'timeline' | 'completed'
}

function buildTimelineSegments<T>(blocks: T[], isFoldable: (block: T) => boolean): ProcessSegment<T>[] {
  const segments: ProcessSegment<T>[] = []
  let processBlocks: T[] = []
  const flush = () => {
    if (processBlocks.length === 0) return
    segments.push({ type: 'process', blocks: processBlocks })
    processBlocks = []
  }
  for (const block of blocks) {
    if (isFoldable(block)) {
      processBlocks.push(block)
      continue
    }
    flush()
    segments.push({ type: 'visible', block })
  }
  flush()
  return segments
}

function buildCompletedSegments<T>(
  blocks: T[],
  isFoldable: (block: T) => boolean,
  isText: (block: T) => boolean,
): ProcessSegment<T>[] {
  const isProcessBlock = blocks.map(
    (block, index) =>
      isFoldable(block) || (isText(block) && hasLaterFoldable(blocks, index, isFoldable)),
  )
  const processBlocks = blocks.filter((_block, index) => isProcessBlock[index])
  const firstProcessIndex = isProcessBlock.findIndex(Boolean)
  const segments: ProcessSegment<T>[] = []
  blocks.forEach((block, index) => {
    if (index === firstProcessIndex) {
      segments.push({ type: 'process', blocks: processBlocks })
      return
    }
    if (isProcessBlock[index]) return
    segments.push({ type: 'visible', block })
  })
  return segments
}

function hasLaterFoldable<T>(blocks: T[], startIndex: number, isFoldable: (block: T) => boolean): boolean {
  for (let index = startIndex + 1; index < blocks.length; index += 1) {
    const candidate = blocks[index]
    if (candidate !== undefined && isFoldable(candidate)) return true
  }
  return false
}

export function buildProcessSegments<T>(blocks: T[], options: ProcessSegmentOptions<T>): ProcessSegment<T>[] {
  if (options.mode === 'timeline') return buildTimelineSegments(blocks, options.isFoldable)
  return buildCompletedSegments(blocks, options.isFoldable, options.isText)
}

export function isActiveProcessSegment<T>(
  segments: ProcessSegment<T>[],
  segmentIndex: number,
  isStreaming: boolean,
): boolean {
  const segment = segments[segmentIndex]
  return isStreaming && segmentIndex === segments.length - 1 && segment?.type === 'process'
}

export function formatProcessDuration(durationMs: number): string {
  const totalSeconds = Math.max(0, Math.round(durationMs / 1000))
  if (totalSeconds < 60) return `${totalSeconds}秒`
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}分${seconds.toString().padStart(2, '0')}秒`
}

export function getProcessSegmentDurationMs<T>(
  segment: ProcessSegment<T>,
  getBlockDurationMs: (block: T) => number | undefined,
): number {
  if (segment.type !== 'process') return 0
  return segment.blocks.reduce((total, block) => total + (getBlockDurationMs(block) ?? 0), 0)
}

/** 错误过程组默认展开；其他组完成后默认折叠。 */
export function hasProcessSegmentError<T>(
  segment: ProcessSegment<T> | undefined,
  hasError: (block: T) => boolean,
): boolean {
  if (segment?.type !== 'process') return false
  return segment.blocks.some(hasError)
}
