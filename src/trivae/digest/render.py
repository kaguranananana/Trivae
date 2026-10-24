"""从已核验的日报数据生成邮件正文，不让模型生成 HTML 或来源链接。"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from trivae.digest.contracts import CATEGORIES

# 裸网址的域名或 IP、端口与后接中文分开识别，路径和查询仍保留原文字面内容。
_RESOURCE_URL = re.compile(r"https?://[A-Za-z0-9.-]+(?::[0-9]+)?(?:[/?#][^\s<>\"'\]\)。，；、！？：）】]*)?")


def render_digest(report: dict[str, Any]) -> tuple[str, str, str]:
    """按真实群归属排版；资源链接靠前，详细正文与可展开原始发言分层。"""

    # 时间窗右边界不包含在本期内，午夜结束的样稿属于前一个自然日。
    day = (datetime.fromisoformat(report["window_end"]) - timedelta(milliseconds=1)).date().isoformat()
    subject = f"Trivae 群聊晚报 · {day} · {len(report['items'])} 个话题"
    lines = [f"# {subject}", "", f"本期读取范围：{report['window_start']} 至 {report['window_end']}",
             f"新增或补齐 {report['root_message_count']} 条群消息，涉及 {report['group_count']} 个群。",
             "内容来自已入库的 QCE 记录，晚于本轮导出的聊天将在后续入库后纳入。", ""]
    # 群名与分组完全沿用实际引用；历史产物即使引用多个群，也会同时标明归属。
    group_names = {source["session_id"]: source["group"] for source in report["sources"].values()}
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for item in report["items"]:
        sessions = tuple(dict.fromkeys(report["sources"][ref["id"]]["session_id"] for ref in item["sources"]))
        grouped.setdefault(sessions, []).append(item)
    sections: list[str] = []
    for sessions, items in grouped.items():
        group_label = "、".join(group_names[session] for session in sessions)
        lines.extend((f"## 群聊：{group_label}", ""))
        topics: list[str] = []
        for item in items:
            lines.extend((f"### {item['title']}", f"方向：{CATEGORIES[item['category']]}", ""))
            # 只展示该话题明确选中的原文链接，避免夹带同一长消息中其他主题的网址。
            urls = [url.rstrip(".,;，。；、") for reference in item["sources"]
                    for url in _RESOURCE_URL.findall(reference["quote"])]
            unique_urls = list(dict.fromkeys(urls))
            links = ""
            if unique_urls:
                lines.append("相关资源链接：")
                lines.extend(f"- {url}" for url in unique_urls)
                lines.append("")
                anchors = "".join(
                    f"<li style='margin:6px 0'><a style='color:#176b5b;text-decoration:underline;"
                    f"overflow-wrap:anywhere' href='{html.escape(url, quote=True)}'>{_escape(url)}</a></li>"
                    for url in unique_urls
                )
                links = ("<div style='background:#f1f6f5;padding:12px 16px;margin:14px 0 20px'>"
                         "<strong style='font-size:14px;color:#176b5b'>相关资源链接</strong>"
                         f"<ul style='padding-left:20px;margin:6px 0;font-size:14px'>{anchors}</ul></div>")
            lines.extend((item["summary"], "", f"值得关注：{item['why_it_matters']}"))
            paragraphs = [_paragraphs(item["summary"]),
                          f"<p style='color:#61736d;font-size:14px'><strong>值得关注：</strong>"
                          f"{_escape(item['why_it_matters'])}</p>"]
            if item["action"]:
                lines.append(f"可以做：{item['action']}")
                paragraphs.append(f"<p style='color:#61736d;font-size:14px'><strong>可以做：</strong>"
                                  f"{_escape(item['action'])}</p>")
            quotes: list[str] = []
            for reference in item["sources"]:
                source = report["sources"][reference["id"]]
                time = source["time"].replace("T", " ").removesuffix("+08:00")
                label = f"{source['group']} · {time} · {source['sender'] or '未知作者'}"
                if source["context_only"]:
                    label += "（前情）"
                quotes.append("<blockquote style='margin:16px 0;padding:0 0 0 12px;border-left:2px solid #dbe6e2'>"
                              f"<p style='font-size:12px;color:#61736d;margin:0'>{_escape(label)}</p>"
                              f"<p style='font-size:13px;margin:4px 0'>{_escape(reference['quote'])}</p></blockquote>")
            # 原文保持完整可核对，但默认不展开，不再用大段摘录挤占讨论正文。
            evidence = ("<details style='margin-top:18px;color:#61736d'>"
                        "<summary style='cursor:pointer;min-height:44px;line-height:44px;font-size:13px'>"
                        f"展开原始发言（{len(item['sources'])} 条引用）</summary>" + "".join(quotes) + "</details>")
            topics.append("<article style='padding:24px 0;border-bottom:1px solid #dbe6e2'>"
                          f"<h3 style='font-size:21px;line-height:1.5;margin:0 0 6px'>{_escape(item['title'])}</h3>"
                          f"<p style='font-size:12px;color:#61736d;margin:0 0 14px'>{CATEGORIES[item['category']]}</p>"
                          + links + "".join(paragraphs) + evidence + "</article>")
            lines.extend(("原始发言可在 HTML 版该话题末尾按需展开。", ""))
        sections.append("<section style='margin:32px 0;background:#fff;padding:20px 24px'>"
                        "<header style='border-left:4px solid #176b5b;padding-left:14px'>"
                        f"<h2 style='font-size:23px;line-height:1.5;margin:0'>{_escape('群聊：' + group_label)}</h2>"
                        f"<p style='font-size:13px;color:#61736d;margin:6px 0 0'>{len(items)} 个话题</p></header>"
                        + "".join(topics) + "</section>")
        lines.append("")
    if not report["items"]:
        empty = "本期没有筛出值得单独展开的内容。" if report["root_message_count"] else "本期没有新增或补齐的群聊消息。"
        lines.extend((empty, ""))
        sections.append(f"<p>{empty}</p>")
    if report["missing_forward_paths"]:
        limitation = f"本期有 {len(report['missing_forward_paths'])} 处转发正文未随导出展开，相关内部内容无法总结。"
        lines.append(limitation)
        sections.append(f"<p style='color:#61736d'>{limitation}</p>")
    intro = "<br>".join(_escape(line) for line in lines[2:5])
    document = (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{_escape(subject)}</title></head>"
        "<body style='margin:0;background:#f1f6f5;color:#203533;"
        "font:16px/1.95 -apple-system,BlinkMacSystemFont,\"PingFang SC\",\"Microsoft YaHei\",sans-serif'>"
        "<main style='max-width:720px;margin:auto;padding:24px 12px;overflow-wrap:anywhere'>"
        f"<h1 style='font-size:28px;line-height:1.5;margin:8px 12px'>群聊晚报 · {day}</h1>"
        f"<p style='color:#61736d;font-size:13px;margin:12px'>{intro}</p>" + "".join(sections)
        + "<p style='color:#61736d;font-size:12px;margin:12px'>保留讨论中的不同意见；群友说法未作外部事实核实。时间均为北京时间。</p>"
        "</main></body></html>"
    )
    return subject, "\n".join(lines), document


def write_digest_files(report: dict[str, Any], directory: Path) -> tuple[str, str, str]:
    """邮件与本地样稿使用同一份正文，便于核对实际发送内容。"""

    subject, text, document = render_digest(report)
    (directory / "report.md").write_text(text, encoding="utf-8")
    (directory / "report.html").write_text(document, encoding="utf-8")
    return subject, text, document


def _escape(value: str) -> str:
    """普通文本在 HTML 中保持字面含义和换行，不解释消息里的标签。"""

    return html.escape(value).replace("\n", "<br>")


def _paragraphs(value: str) -> str:
    """详细总结按自然段排版，保留单段内的换行和原有文字。"""

    return "".join(f"<p style='margin:0 0 16px'>{_escape(paragraph)}</p>"
                   for paragraph in value.split("\n\n") if paragraph.strip())
