"""For each process stack file in <level dir>/stacks (PRISM_STACK_DUMPS=1, F1.1): the innermost frames of the main thread at each dump.

Usage: python3 polyaxon/stack_summary.py <level dir>
"""
import sys,glob,re,os
for f in sorted(glob.glob(sys.argv[1]+"/stacks/*.txt")):
    lines=open(f).read().split("\n")
    name=lines[0].lstrip("# ")
    dumps=[];cur=None;inmain=False
    for l in lines[1:]:
        if l.startswith("Current thread"): inmain=True; cur=[]; continue
        if l.startswith("Thread 0x"): 
            if inmain and cur is not None: dumps.append(cur)
            inmain=False; continue
        if inmain and l.strip().startswith("File"):
            m=re.search(r'File "([^"]+)", line (\d+) in (\S+)',l)
            if m: cur.append(f"{os.path.basename(m[1])}:{m[2]} {m[3]}")
        if inmain and l.strip()=="" and cur: dumps.append(cur); inmain=False; cur=None
    if inmain and cur: dumps.append(cur)
    print(name)
    for d in dumps: print("   ", " <- ".join(d[:4]))
