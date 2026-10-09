"""Dump a CST ModelHistory.json into reviewable plain text."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    source = Path(sys.argv[1])
    target = Path(sys.argv[2])
    document = json.loads(source.read_text(encoding="utf-8-sig"))
    chunks: list[str] = []
    for block in document["history"]:
        code = block["code"]
        if isinstance(code, list):
            code = "\n".join(str(line) for line in code)
        chunks.append("=" * 72)
        chunks.append(f"CAPTION: {block['caption']}")
        chunks.append("=" * 72)
        chunks.append(code)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(chunks) + "\n"
    target.write_text(text, encoding="utf-8")
    print(f"wrote {target} ({len(text)} chars, {len(document['history'])} blocks)")


if __name__ == "__main__":
    main()
