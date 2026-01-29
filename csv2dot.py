"""
Usage: python csv2dot.py < input.csv > output.dot
This uses Unix pipes and redirection instead of file IO.
"""

import csv;
import sys;

print("digraph CallGraph {");
print("  rankdir=LR;");
print('  node [shape=box, fontname="monospace"];');

r = csv.DictReader(sys.stdin);
for row in r:
    print(f'  "{row["source"]}" -> "{row["target"]}";');

print("}");

