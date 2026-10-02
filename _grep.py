# -*- coding: utf-8 -*-
import io
import sys

path, kw = sys.argv[1], sys.argv[2]
for i, line in enumerate(io.open(path, encoding="utf-8").read().splitlines(), 1):
    if kw in line:
        print(i, line.rstrip()[:170])
