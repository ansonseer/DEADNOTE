#!/usr/bin/env python3
"""Count Chinese characters in markdown files, excluding fenced code blocks.
Usage: python3 count.py chapters/*.md
"""
import re, sys
for p in sys.argv[1:]:
    t = open(p, encoding="utf-8").read()
    body = re.sub(r"```.*?```", "", t, flags=re.S)
    n = len(re.findall(r"[一-鿿]", body))
    print(f"{n:6d}  {p}")
