---
name: openlabs-journal-mail-triage
description: Classify the journal letters the journal_mail rules could not settle (held, undecided, unmatched) from their redacted briefs, with verbatim evidence, for a person to check. Use only in an OpenLabs journal_mail_triage task.
---

# OpenLabs journal mail triage

The packet at the input path (`openlabs.journal_mail_triage_packet.v1`) lists `letters`, each
`{key, letter}`. A letter is a brief of one message in the paper service's mailbox that the
deterministic rules could not settle. A person registers every outcome on the management site;
your answer only tells them what you read. It changes nothing by itself, so say plainly when a
letter is not a decision or when you cannot tell.

A brief holds:

- `subject`, `sender_domain`, `received_at`;
- `sentences`: the letter's sentences that may bear on a decision, in order, with addresses,
  links, phone numbers and names replaced by `[email]`, `[link]`, `[phone]`, `[name]`. The
  letter may be a forward or a reply; the decision is the journal's, not the colleague's note;
- `manuscript_ids`: numbers the rules found in the letter;
- `rules`: what the rules made of it (`kind`: `unmatched` no paper matched, `ambiguous` several,
  `conflict` contradictory decisions, `no_decision` none recognised, `many_numbers`,
  `parse_failed`; `decisions`: the decision words they matched, which can be wrong, e.g. an
  "accepted" in an author declaration or a conditional sentence);
- `candidates`: papers on the site the letter may be about (`paper_id`, `title`, `attempts` with
  journal, manuscript number and status). It may be empty.

## What to answer for each letter

`category`, exactly one of:

| category | the letter says |
|---|---|
| `submitted` | the journal received a new submission (receipt, acknowledgement, number assigned) |
| `resubmitted` | the journal received a revised version |
| `rejected` | the journal declines the paper after review or without saying |
| `desk_reject` | declined by the editor without external review (out of scope, not sent to referees) |
| `major_revision` / `minor_revision` | a revision is requested (use `major_revision` when the grade is not stated) |
| `accepted` | this paper is accepted (not an author declaration, a condition, an abstract-only slot or another paper) |
| `proof` | proofs of the accepted paper are ready or due |
| `transfer_offer` | an offer or reminder to transfer the paper to another journal |
| `not_a_decision` | anything else about the paper or no paper at all: reminders, invitations, copyright, APC, newsletters, calls, a colleague's note |
| `other` | an editorial message that fits none of the above (withdrawal, under review, editor assigned) |

`paper_id`: a `paper_id` from that letter's `candidates` only when the title or manuscript
number in the letter identifies it; otherwise `null`. Do not guess from the journal alone.

`manuscript_id`: the journal's number for the paper as written in the letter, or `null`.

`due`: the revision or proof deadline as `YYYY-MM-DD` when the letter states a date, else `null`
(never computed from "within N days").

`confidence`: from 0 to 1, how sure you are of the category.

`evidence_quotes`: one to three passages, each 8 to 400 characters, copied character for
character from that letter's `subject` or one of its `sentences` (keep `[name]` and the other
placeholders as they are; do not join two sentences, fix spelling or translate). The control
plane discards an answer whose quotes are not found verbatim.

`note` (optional): at most 300 characters, for a person (e.g. "forward of a colleague's
decision; not this paper").

## Result

Write the result bundle with `status: "completed"` and one extra top-level field:

```json
"journal_triage": [
  {"key": "uid:123", "category": "rejected", "paper_id": null, "manuscript_id": "ABC-D-26-00012",
   "due": null, "confidence": 0.9, "evidence_quotes": ["We regret to inform you that ..."]}
]
```

One object per letter of the packet, with exactly these keys (and `note` if you use it). Use
`artifacts: []` and `claims: []`. Read only the packet; do not open a mailbox, a website or any
other file, and write nothing besides the result bundle.
