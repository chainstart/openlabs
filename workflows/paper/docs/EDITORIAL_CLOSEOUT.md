# Editorial bridge after a legacy closeout

This opt-in path was authorized on 2026-09-11 for three journal retargets.
It is not a global score, scientific, evidence, or revision-budget exemption.

`editorial_closeout_preparation` binds a preparation JSON and an exact per-paper,
source/target-version user authorization under `registry/quality-gate-exceptions`.
The preparation binds a historical registry and full source/PDF archive, new
source/PDF hashes, metadata fingerprints, complete source delta and cover-letter
context. Archives stay in artifact storage; immutable hashes and text records
are Git-frozen before handoff.

`paper_writing.editorial_closeout.inspect` reconstructs the old manuscript and
registry in a private read-only Bubblewrap mount namespace and runs the ORIGINAL
minor/targeted validators, including their raw reviews, previous addendum and
support bindings. No live source is replaced and no historical judgment is
rewritten. Unsupported baselines and unavailable isolation fail closed.

Only main-TeX, generated bibliography and author wrapper changes are eligible.
All scientific source files and complete support metadata/payload must remain
unchanged. New official publisher style files require an exact filename, HTTPS
publisher source and SHA-256 in the per-paper authorization. This is merely a
scope tripwire: the independent reviewer must assess every changed hunk, global
template interface, declaration, bibliography and affected visual layout.

The shared router returns `closeout_delta` only after this inspection. The referee
runs fresh, ephemeral and read-only, with no author-session state, prior scores,
or new full-paper scoring. Prior issue/resolution text is retained. The frozen
packet, executable invocation and result hashes are bound into the certificate.
An unresolved or escalating judgment does not advance readiness. Optional
polishing remains separate from mandatory blockers.

The new total is the LAST READY release's complete round count plus one, not the
old original full-review count plus one. Existing revision-budget validation
applies; each increase still requires its own explicit human authorization.
Original score, CAS decision and source quality gate are preserved exactly.
Declaration, support, style, clean-build and archive checks remain mandatory.
Handoff replays this entire chain and requires Git-frozen evidence. No gate
operation submits a manuscript to a journal or performs a remote upload.

A narrowly checked author-side bibliography closeout may retain an unresolved
referee record when its sole blocker is lost electronic bibliography locators,
scientific preservation is explicitly affirmed, and the only final source edits
undo `plain` to the previous `elsarticle-num` style and regenerate a bibliography
byte-identical to the previous ready bibliography. The reviewed intermediate
source/PDF remain independently hash-bound; no other change or blocker fits this
path. It adds no independent judgment and never rewrites the referee's verdict.

Implementation: `paper_writing/editorial_closeout.py`. Ordinary delta and minor
closeout behavior is unchanged for records without this explicit opt-in.
