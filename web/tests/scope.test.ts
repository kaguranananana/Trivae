import { describe, expect, it } from 'vitest'
import {
  compileNavigationScope,
  describeScope,
  navigationSelectionsEqual,
  normalizeSessionIds,
  restoreNavigationScope,
  scopeKey,
  selectableScopesEqual,
} from '@/utils/scope'
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

describe('navigation selection compilation', () => {
  it('compiles unselected to null without an all fallback', () => {
    expect(compileNavigationScope(null)).toBeNull()
    expect(compileNavigationScope({ kind: 'all' })).toEqual({ mode: 'all' })
    expect(compileNavigationScope({ kind: 'session', sessionId: 's1' }))
      .toEqual({ mode: 'sessions', session_ids: ['s1'] })
  })

  it('restores legal navigation scopes from immutable conversation scopes', () => {
    expect(restoreNavigationScope({ mode: 'all' }, sessions)).toEqual({ kind: 'all' })
    expect(restoreNavigationScope({ mode: 'sessions', session_ids: ['s2'] }, sessions))
      .toEqual({ kind: 'session', sessionId: 's2' })
  })

  it('keeps multi-session, unknown-session, and legacy scopes out of primary navigation', () => {
    expect(restoreNavigationScope({ mode: 'sessions', session_ids: ['s1', 's2'] }, sessions)).toBeNull()
    expect(restoreNavigationScope({ mode: 'sessions', session_ids: ['missing'] }, sessions)).toBeNull()
    expect(restoreNavigationScope(null, sessions)).toBeNull()
  })

  it('compares navigation selections structurally', () => {
    expect(navigationSelectionsEqual(null, null)).toBe(true)
    expect(navigationSelectionsEqual(null, { kind: 'all' })).toBe(false)
    expect(navigationSelectionsEqual({ kind: 'all' }, { kind: 'all' })).toBe(true)
    expect(navigationSelectionsEqual({ kind: 'all' }, { kind: 'session', sessionId: 's1' })).toBe(false)
    expect(navigationSelectionsEqual({ kind: 'session', sessionId: 's1' }, { kind: 'session', sessionId: 's1' }))
      .toBe(true)
    expect(navigationSelectionsEqual({ kind: 'session', sessionId: 's1' }, { kind: 'session', sessionId: 's2' }))
      .toBe(false)
  })
})
