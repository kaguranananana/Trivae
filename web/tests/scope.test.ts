import { describe, expect, it } from 'vitest'
import { describeScope, normalizeSessionIds, scopeKey, selectableScopesEqual } from '@/utils/scope'
import type { SessionDTO } from '@/types/contracts'

const sessions: SessionDTO[] = [
  { session_id: 's1', platform: 'wechat', name: '产品群', chat_type: 'group' },
  { session_id: 's2', platform: 'wechat', name: '研发群', chat_type: 'group' },
  { session_id: 's3', platform: 'wechat', name: '运营群', chat_type: 'group' },
]

describe('scope helpers', () => {
  it('normalizes duplicate and reordered session IDs into one stable identity', () => {
    expect(normalizeSessionIds(['s2', 's1', 's2'])).toEqual(['s1', 's2'])
    expect(scopeKey({ mode: 'sessions', session_ids: ['s2', 's1', 's2'] }))
      .toBe('sessions:["s1","s2"]')
    expect(selectableScopesEqual(
      { mode: 'sessions', session_ids: ['s2', 's1'], max_results: 100 },
      { mode: 'sessions', session_ids: ['s1', 's2'], max_results: 5_000 },
    )).toBe(true)
  })

  it('keeps all and legacy unmarked scopes distinct', () => {
    expect(scopeKey(null)).toBe('unmarked')
    expect(scopeKey({ mode: 'all' })).toBe('all')
    expect(describeScope(null, sessions)).toEqual({ label: '未标记范围', title: '未标记范围' })
    expect(describeScope({ mode: 'all' }, sessions)).toEqual({ label: '全部群聊', title: '全部群聊' })
  })

  it('builds compact labels while retaining complete names in the tooltip', () => {
    expect(describeScope({ mode: 'sessions', session_ids: ['s1'] }, sessions))
      .toEqual({ label: '产品群', title: '产品群' })
    expect(describeScope({ mode: 'sessions', session_ids: ['s2', 's1'] }, sessions))
      .toEqual({ label: '产品群 + 研发群', title: '产品群 + 研发群' })
    expect(describeScope({ mode: 'sessions', session_ids: ['s3', 's1', 's2'] }, sessions))
      .toEqual({ label: '3 个群聊', title: '产品群 + 研发群 + 运营群' })
  })

  it('uses the original ID for an unknown historical session', () => {
    expect(describeScope({ mode: 'sessions', session_ids: ['missing-session'] }, sessions))
      .toEqual({ label: 'missing-session', title: 'missing-session' })
  })
})
