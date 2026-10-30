#!/usr/bin/env python3
"""Append a mood / reading / idea entry to the daily journal file.

Usage:
    python record.py --type mood    --text "今天很踏实"
    python record.py --type reading --text "《置身事内》P88 土地财政..." --tags 经济,摘录
    python record.py --type idea    --text "短视频选题：..." --date 2026-09-16
    python record.py --type idea    --text "..." --dir C:/Users/me/journal
"""

import argparse
import datetime
import os
import sys

TITLES = {"mood": "心情", "reading": "读书", "idea": "灵感"}
ORDER = ["心情", "读书", "灵感"]
WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def parse(content):
    """Split a journal file into (header, [(title, body_lines), ...])."""
    header_lines = []
    sections = []
    current = None
    for line in content.split("\n"):
        if line.startswith("## "):
            current = [line[3:].strip(), []]
            sections.append(current)
        elif current is None:
            header_lines.append(line)
        else:
            current[1].append(line)
    return "\n".join(header_lines), sections


def render(header, sections):
    known = sorted(
        (s for s in sections if s[0] in ORDER), key=lambda s: ORDER.index(s[0])
    )
    other = [s for s in sections if s[0] not in ORDER]
    blocks = []
    for title, body_lines in known + other:
        text = "\n".join(body_lines).rstrip("\n")
        blocks.append("## %s\n%s\n" % (title, text))
    body = "\n".join(blocks)
    head = header.rstrip("\n")
    return (head + "\n\n" + body) if head else body


def upsert(content, title, line, timestamp):
    header, sections = parse(content)
    for sec in sections:
        if sec[0] == title:
            body = "\n".join(sec[1]).rstrip("\n")
            newline = "%s %s" % (timestamp, line)
            sec[1] = (((body + "\n") if body else "") + newline).split("\n")
            return render(header, sections)
    sections.append([title, ["%s %s" % (timestamp, line)]])
    return render(header, sections)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", required=True, choices=sorted(TITLES))
    ap.add_argument("--text", required=True)
    ap.add_argument("--tags", default="")
    ap.add_argument("--date", default="")
    ap.add_argument("--dir", default="")
    args = ap.parse_args()

    day = (
        datetime.date.fromisoformat(args.date)
        if args.date
        else datetime.date.today()
    )
    root = args.dir or os.path.join(os.path.expanduser("~"), ".workbuddy", "journal")
    path = os.path.join(root, day.strftime("%Y-%m"), day.strftime("%Y-%m-%d") + ".md")

    now = datetime.datetime.now()
    stamp = now.strftime("%H:%M")
    text = " ".join(args.text.split())
    tags = [t.strip().lstrip("#") for t in args.tags.replace("，", ",").split(",") if t.strip()]
    if tags:
        text = "%s  %s" % (text, " ".join("#" + t for t in tags))

    title = TITLES[args.type]
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        content = upsert(content, title, text, stamp)
    else:
        header = "# %s 周%s" % (day.isoformat(), WEEKDAYS[day.weekday()])
        content = render(header, [[title, ["%s %s" % (stamp, text)]]])
        os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)

    print("已记入 %s ｜ %s ｜ %s" % (path, title, stamp))


if __name__ == "__main__":
    main()
