"""Inline rendered prompt files into impl.md (spec tooling only).

    python3 pm/specs/pr-b491378/tools/build_impl.py          # rewrite impl.md
    python3 pm/specs/pr-b491378/tools/build_impl.py --check  # exit 1 on drift

Every block of the form

    <!-- include: prompts/proposed/NAME.txt -->
    ~~~~text
    ...
    ~~~~
    <!-- /include -->

gets the file's exact content between the fences, so the full prompt text in
impl.md §1 is byte-identical to the rendered file (and to the diff inputs).
"""
import re
import sys
from pathlib import Path

SPEC = Path(__file__).resolve().parents[1]
IMPL = SPEC / "impl.md"
BLOCK = re.compile(
    r"(<!-- include: (?P<path>[^ ]+) -->\n~~~~text\n)(?P<body>.*?)(~~~~\n<!-- /include -->)",
    re.S)


def render(text: str) -> str:
    def sub(m):
        body = (SPEC / m.group("path")).read_text()
        if not body.endswith("\n"):
            body += "\n"
        assert "~~~~" not in body, m.group("path")
        return m.group(1) + body + m.group(4)
    return BLOCK.sub(sub, text)


def main():
    text = IMPL.read_text()
    out = render(text)
    n = len(BLOCK.findall(text))
    if "--check" in sys.argv:
        if out != text:
            print(f"impl.md is out of date with prompts/ ({n} include blocks)")
            sys.exit(1)
        print(f"impl.md matches prompts/ ({n} include blocks)")
        return
    IMPL.write_text(out)
    print(f"impl.md rebuilt ({n} include blocks)")


if __name__ == "__main__":
    main()
