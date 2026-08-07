# Independent audit: K4,r9 has no uniform fixed recovery rank

Verdict: **PASS**, as a theorem about the single fixed actual
`(k,r,u)=(4,9,12)` odd-`j` orbit.  The quantifier is

```text
for every fixed R>=4, there exists one odd j_R such that the same member
has gamma_3,...,gamma_R<0.
```

It is not `exists j forall R`, and it does not settle the public Erdős 776
antichain question.

The reconstruction did not import the author verifier.  It used a separate
standard-library greedy Macaulay engine and the raw direct orbit.

## 1. Actual orbit and the missing base link

The campaign's underlying K4,r9 family is

```text
h_j=112*2^(j-1),        q_j=(2h_j+4)/3,
b=q+4,                  n=C(q,2)+9,
H_0=C(b,2)+1,           tau=H_0-n=4q-2,
```

for odd `j`.  Since `j-1` is even, `2^(j-1)=1 (mod 3)`, so `q_j` is an
even integer.  Also

```text
C(b-1,2)+2-n=2h,
q_(j+2)=4q_j-4>q_j,
```

so these are actual dyadic members and their `q` values are unbounded.

Writing `H=5q/2=h+b-2`, the direct rank-three states are

```text
x_3=C(H,3)+C(q,2)+9,
y_3=C(H+1,3)+C(q+1,2)+12.
```

For sufficiently large `q` these are strict canonical words.  Raising them
and subtracting `tau` gives

```text
x_4=C(H,4)+C(q-1,3)+C(q-5,2)+25,
y_4=C(H+1,4)+C(q,3)+C(q-4,2)+58.
```

Thus `(A_4,B_4)=(25,58)` is connected to the raw actual orbit, rather than
being a free formal initial condition.  The author checker starts at this
base and does not itself test this link; the independent checker does.

The same direct words give

```text
gamma_3=23-4q.
```

## 2. Universal stable-word induction

Assume the displayed rank-`n` words are strict canonical words.  All leading
terms raise directly.  On the x side put `d=5n-15` and `t=q-d`.  Pascal's
identity reduces the only bottom borrow to

```text
C(t-1,2)-C(t-5,2)-4q+3
 = 4t-14-4q+3
 = -20n+49.
```

Consequently the new constant is

```text
A_(n+1)=C(A_n,2)-(20n-49).
```

On the y side `d=5n-16` and subtraction is `4q-2`, so the analogous residual
is `-20n+52`, giving

```text
B_(n+1)=C(B_n,2)-(20n-52).
```

These are identities for every integer `n`, not conclusions from the finite
rank table.

## 3. Positivity, strict ordering, and nonnegative tails

The constants are positive uniformly.  At rank four,
`A_4=25=4*4+9` and `B_4>=4*4+9`.  If a current A-side constant is at least
`4n+9`, then

```text
C(4n+9,2)-(20n-49)-(4(n+1)+9)
 = 2(4n^2+5n+36)>0.
```

The B recurrence subtracts three less.  Induction therefore gives
`A_n,B_n>=4n+9>0` for every `n>=4`.

For any fixed `R`, impose the finitely many inequalities

```text
q-(5n-15)>A_n,   q-(5n-16)>B_n       (4<=n<=R).
```

They imply the bottom strict ordering; every higher adjacent pair differs by
at least one (in fact normally four or five), `H>q`, and every top index is at
least its lower index.  Hence both words are strict canonical words.  The
transition identities express each next state as a sum of nonnegative
binomial terms in its next strict word, which rules out a hidden negative
tail or an unrecorded borrow.

Because the set of requirements is finite and `q_j` is unbounded on odd
`j`, one actual odd member satisfies all order requirements simultaneously.

## 4. Surplus and simultaneous sign choice

Every nonconstant top in the y word is exactly one more than its aligned
x top.  Applying Pascal cancellation to `U_n(y_n)-U_n(x_n)` reproduces all
nonconstant terms of `x_n`; after subtracting `x_n` only the bottom constants
remain.  Since `tau=4q-2`,

```text
gamma_n=C(B_n,2)-C(A_n+1,2)+2-4q
       =B_(n+1)-A_(n+1)-A_n-1-4q.
```

For fixed `R`, all constants for `4<=n<=R` are finite.  Add their finitely
many strict sign thresholds to the ordering thresholds and choose one odd
`j_R` above the maximum.  That same actual member has
`gamma_3,...,gamma_R<0`.  This proves the stated `forall R exists j_R`
quantifier and no stronger exchanged-quantifier statement.

## 5. Independent machine replay

The independent checker chose the first odd member above the combined
ordering/sign bound for `R=12`: `j=2469`, with a 2475-bit `q`.  Starting from
the raw rank-three integers, it greedily reconstructed every complete word
through rank 12, matched the proposed stable words at ranks 4 through 12,
checked every surplus was negative, and checked every next state was
nonnegative.  It also checked the first constants and the positivity-growth
guard through rank 20.

Command:

```text
AMRA_MEMORY_KIB=3145728 AMRA_TIMEOUT_SECONDS=180 LEAN_NUM_THREADS=1 \
  amra-research-loop/scripts/run_bounded.sh python3 \
  amra-research-loop/campaigns/erdos-776-adaptive-round4/audit/verify_k4r9_no_fixed_rank_independent.py
```

The run exited zero.  The script SHA-256 is
`3057136c0cea72a67c8e31aef9bc91ce7a43290a7cbf685d00781b907effd040`.

The author verifier also exits zero under the same 3 GiB/180 s cap and its
symbolic identities agree with the reconstruction.  Two reproducibility
limitations do not affect the mathematical verdict: it imports external
`sympy` despite the package's standard-library preference, and its numerical
word test uses a large non-dyadic `q` rather than replaying the raw actual
orbit.  The independent checker removes both limitations.

## 6. Scope firewall

The result proves that no finite recovery-rank bound depending only on the
fixed pair `(k,r)=(4,9)` can work uniformly over this odd-`j` orbit.  Taking
`R=42` also refutes a uniform pre-rank-42 seed obtained merely by waiting
along this orbit.  It does not exhibit one finite state negative at every
rank, refute parameter-dependent eventual recovery of each individual state,
or establish/refute the public Erdős 776 statement through another
construction.
