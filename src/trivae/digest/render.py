"""从已核验的日报数据生成邮件正文，不让模型生成 HTML 或来源链接。"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from trivae.digest.contracts import CATEGORIES


def render_digest(report: dict[str, Any]) -> tuple[str, str, str]:
    """同时输出主题、纯文本和移动端可读的 HTML 邮件。"""

    # 时间窗右边界不包含在本期内，午夜结束的样稿属于前一个自然日。
    day = (datetime.fromisoformat(report["window_end"]) - timedelta(milliseconds=1)).date().isoformat()
    subject = f"Trivae 群聊晚报 · {day} · {len(report['items'])} 条精选"
    lines = [f"# {subject}", "", f"本期读取范围：{report['window_start']} 至 {report['window_end']}",
             f"新增或补齐 {report['root_message_count']} 条群消息，涉及 {report['group_count']} 个群。",
             "内容来自已入库的 QCE 记录，晚于本轮导出的聊天将在后续入库后纳入。", ""]
    sections: list[str] = []
    for index, item in enumerate(report["items"], start=1):
        title = f"{index}. {item['title']}"
        lines.extend((f"## {title}", f"方向：{CATEGORIES[item['category']]}", "", item["summary"], "",
                      f"值得关注：{item['why_it_matters']}"))
        paragraphs = [f"<p>{_escape(item['summary'])}</p>",
                      f"<p><strong>值得关注：</strong>{_escape(item['why_it_matters'])}</p>"]
        if item["action"]:
            lines.append(f"可以做：{item['action']}")
            paragraphs.append(f"<p><strong>可以做：</strong>{_escape(item['action'])}</p>")
        quotes: list[str] = []
        urls: list[str] = []
        for reference in item["sources"]:
            source = report["sources"][reference["id"]]
            label = f"{source['group']} · {source['time']} · {source['sender'] or '未知作者'}"
            if source["context_only"]:
                label += "（前情）"
            lines.extend((f"来源：{label}", f"> {reference['quote']}"))
            quotes.append(f"<div style='margin:10px 0;padding-left:12px;border-left:3px solid #ced8e3'>"
                          f"<small>{_escape(label)}</small><p>{_escape(reference['quote'])}</p></div>")
            # 链接只取自真实来源正文，不能把模型编造的网址变成可点击资源。
            urls.extend(re.findall(r"https?://[^\s<>\"'\]\)]+", source["text"]))
        unique_urls = list(dict.fromkeys(url.rstrip("，。；、") for url in urls))
        for url in unique_urls:
            lines.append(f"原文链接：{url}")
        links = " ".join(f"<p><a href='{html.escape(url, quote=True)}'>{_escape(url)}</a></p>" for url in unique_urls)
        badge = "今日精选 · " if index <= 5 else "延伸阅读 · "
        sections.append(
            "<section style='background:#fff;border:1px solid #e3e8ef;border-radius:12px;padding:20px;margin:18px 0'>"
            f"<small style='color:#496581'>{badge}{CATEGORIES[item['category']]}</small>"
            f"<h2 style='font-size:19px;margin:8px 0 12px'>{_escape(title)}</h2>"
            + "".join(paragraphs + quotes) + links + "</section>"
        )
        lines.append("")
    if not report["items"]:
        empty = "本期没有筛出值得单独展开的内容。" if report["root_message_count"] else "本期没有新增或补齐的群聊消息。"
        lines.extend((empty, ""))
        sections.append(f"<p>{empty}</p>")
    if report["missing_forward_paths"]:
        limitation = f"本期有 {len(report['missing_forward_paths'])} 处转发正文未随导出展开，相关内部内容无法总结。"
        lines.append(limitation)
        sections.append(f"<p style='color:#6b7280'>{limitation}</p>")
    intro = "<br>".join(_escape(line) for line in lines[2:5])
    document = (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'></head>"
        "<body style='margin:0;background:#f4f6f9;color:#243346;font:15px/1.8 -apple-system,BlinkMacSystemFont,sans-serif'>"
        "<main style='max-width:720px;margin:auto;padding:24px 16px;overflow-wrap:anywhere'>"
        f"<p style='color:#496581;letter-spacing:2px'>TRIVAE · 群聊晚报</p><h1 style='font-size:26px'>{day}</h1>"
        f"<p style='color:#66758a;font-size:13px'>{intro}</p>" + "".join(sections)
        + "<p style='color:#66758a;font-size:12px'>保留讨论中的不同意见；群友说法未作外部事实核实。时间均为北京时间。</p>"
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
