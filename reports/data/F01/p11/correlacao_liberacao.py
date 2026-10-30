"""For each deactivation: was release slow (>5 s)? mean GPU util during it; activations in progress during it."""
import re,sys,datetime,csv
def ts(s,fmt="%Y-%m-%d %H:%M:%S.%f"): return datetime.datetime.strptime(s,fmt).timestamp()
lvl=sys.argv[1]
log=open(lvl+"/server_file.log",errors='replace').read().splitlines()
deacts=[];acts=[];act_start={}
for line in log:
    m=re.match(r"\[(\S+ \S+) GPU=0 Worker (\d+) \((\S+)\) TP=0\] (.*)",line)
    if not m: continue
    t=ts(m[1]); w=m[2]; msg=m[4]
    if msg.startswith("Processing activate request"): act_start[w]=t
    elif msg.startswith("Scheduler activated. Activation takes") and w in act_start: acts.append((act_start.pop(w),t))
    d=re.match(r"Deactivate time cost: ([0-9.]+)s \(release=([0-9.]+)",msg)
    if d: deacts.append((t-float(d[1]),t-float(d[1])+float(d[2]),float(d[2])))
gpu=[]
for r in csv.reader(open(lvl+"/gpu.csv")):
    try: gpu.append((ts(r[0].strip(),"%Y/%m/%d %H:%M:%S.%f"),float(r[3]),float(r[1])/1024))
    except Exception: pass
for s,e,rel in deacts:
    u=[x for t,x,_ in gpu if s<=t<=e] or [x for t,x,_ in gpu if abs(t-s)<1.5]
    mem=[mm for t,_,mm in gpu if abs(t-s)<1.5]
    na=sum(1 for a,b in acts if a<e and b>s)
    print("SLOW" if rel>5 else "ok", f"{sum(u)/len(u):.0f}" if u else "nan", na, f"{max(mem):.1f}" if mem else "nan", f"{rel:.1f}")
