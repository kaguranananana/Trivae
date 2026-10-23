/** 已知协议状态的中文展示；原始字段仍保存在运行详情。 */
const limitationLabels: Record<string, string> = {
  tool_result_partial: '部分工具只返回了部分结果。',
  retrieval_partial: '检索未覆盖全部相关消息。',
  retrieval_truncated: '检索结果存在截断，可能遗漏较早或较长的内容。',
  'coverage:partial': '检索未覆盖全部相关消息。',
  'coverage:unknown': '本次检索的完整覆盖情况尚不明确。',
  unexpanded_forward_content: '部分转发正文缺失，无法核对完整内容。',
  insufficient_evidence: '可恢复文本中未命中，现有材料不足以判断完整范围。',
}

export function readableLimitations(values: readonly string[]): string[] {
  // 去重只发生在展示层，原始限制与其顺序仍留在回答对象中。
  return [...new Set(values.map((value) => limitationLabels[value] ?? (value.startsWith('tool_error:') ? `部分工具执行失败（${value.slice(11)}）。` : value)))]
}

const toolLabels: Record<string, string> = {
  lexical_search: '搜索关键词', semantic_search: '查找相关讨论', search_messages: '搜索消息',
  get_recent_messages: '读取近期消息', get_message_context: '查看消息上下文',
  get_schema: '查看数据结构', find_members: '查找群成员', execute_sql: '统计与查询', run_sql: '统计与查询',
}

export function toolLabel(name: string): string {
  // 未知工具名称保留，避免给新协议编造含义。
  return toolLabels[name] ?? name
}
