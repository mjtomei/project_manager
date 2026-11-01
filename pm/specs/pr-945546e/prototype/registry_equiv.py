import os
import re, subprocess, sys
def git(*a): return subprocess.run(["git",*a],cwd=os.environ.get("REPO", "."),capture_output=True,text=True).stdout
ENTRY=re.compile(r"^- id: (\S+)"); TOP=re.compile(r"^(\w+):")
def entries(text):
    out={}; sec=None; cur=None; buf=[]
    def flush():
        if cur: out[cur]="\n".join(buf)
    for line in text.splitlines():
        m=TOP.match(line)
        if m:
            flush(); sec=m.group(1); cur=sec if sec=="project" else None; buf=[]
        m2=ENTRY.match(line)
        if m2 and sec in ("prs","plans"):
            flush(); cur=f"{sec}:{m2.group(1)}"; buf=[]
        buf.append(line)
    flush(); return out
a,b=sys.argv[1],sys.argv[2]
mb=git("merge-base",a,b).strip()
E0,EA,EB=(entries(git("show",f"{r}:pm/project.yaml")) for r in (mb,a,b))
chA={k for k in set(E0)|set(EA) if E0.get(k)!=EA.get(k)}
chB={k for k in set(E0)|set(EB) if E0.get(k)!=EB.get(k)}
both=chA&chB
same=[k for k in both if EA.get(k)==EB.get(k)]
diff=[k for k in both if EA.get(k)!=EB.get(k)]
print(f"A changed {len(chA)} entries, B {len(chB)}; both {len(both)}: identical {len(same)}, different {len(diff)}: {sorted(diff)[:10]}")
