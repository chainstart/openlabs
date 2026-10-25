from common import *
import collections
class UnionFind:
    def __init__(self,n):self.p=list(range(n));self.size=[1]*n
    def find(self,x):
        while self.p[x]!=x:self.p[x]=self.p[self.p[x]];x=self.p[x]
        return x
    def union(self,a,b):
        a,b=self.find(a),self.find(b)
        if a==b:return
        if self.size[a]<self.size[b]:a,b=b,a
        self.p[b]=a;self.size[a]+=self.size[b]
def canonical(s):return min(s,s.translate(str.maketrans('ACGT','TGCA'))[::-1])
def groups(records):
    """Genomic/LD components, plus exhaustive >=99% whole-insert identity."""
    uf=UnionFind(len(records));indexes={};blocks={}
    reverse=lambda s:s.translate(str.maketrans('ACGT','TGCA'))[::-1]
    for i,r in enumerate(records):
        keys=[('block',r['chrom'],b) for b in range(r['start']//1000000,(r['end']-1)//1000000+1)]
        if r.get('index_signal'):keys.append(('signal',r['index_signal']))
        keys.append(('sequence',canonical(r['sequence'])))
        for key in keys:
            if key in indexes:uf.union(i,indexes[key])
            else:indexes[key]=i
        s=r['sequence'];n=len(s);maxdiff=n//100;parts=maxdiff+1
        # <=maxdiff substitutions imply at least one of parts disjoint blocks
        # is exactly equal. Both orientations stored, then full sequence checked.
        candidates=set()
        for orient in (s,reverse(s)):
            for b in range(parts):
                lo=b*n//parts;hi=(b+1)*n//parts
                key=(n,b,orient[lo:hi]);candidates.update(blocks.get(key,()))
        for j in candidates:
            if uf.find(i)==uf.find(j):continue
            t=records[j]['sequence']
            if min(sum(a!=b for a,b in zip(s,t)),sum(a!=b for a,b in zip(s,reverse(t))))<=maxdiff:uf.union(i,j)
        for orient in (s,reverse(s)):
            for b in range(parts):
                key=(n,b,orient[b*n//parts:(b+1)*n//parts]);blocks.setdefault(key,[]).append(i)
    by=collections.defaultdict(list)
    for i,r in enumerate(records):by[uf.find(i)].append(i)
    result={}
    for component in by.values():
        members=sorted(records[i]['dataset']+':'+records[i]['sample_id'] for i in component)
        g=hashlib.sha256('\n'.join(members).encode()).hexdigest()[:20]
        u=int(hashlib.sha256(('replan-R2-20261021:'+g).encode()).hexdigest()[:12],16)/16**12
        split='train' if u<.4 else ('validation' if u<.6 else 'test')
        for i in component:result[i]=(g,split)
    return result
