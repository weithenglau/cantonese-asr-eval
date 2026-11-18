# Cantonese ASR evaluation results

Model: `gpt-4o-transcribe-apac` (docx vs human-verified docx ground truth).
Run: see [README.md](README.md) (`--map-colloquial --gt-verified`, all five pairs in one folder run).
Mappings used: see [docs/mappings.txt](docs/mappings.txt). Raw data: `results/all/results.csv`
(numeric cells: rates are fractions, e.g. 0.5135 = 51.35%). Readable error diffs per call:
`results/all/diff_*.txt`.

## Per call

| Call | Files | Ref tokens | Hyp tokens | CER raw | CER mapped | CER mapped, fillers dropped | Sub | Del | Ins | Longest deleted run (position) | Entity P / R | Repeated passages |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | groundtruth / transcription (2026-08-11) | 777 | 741 | 70.48% | **51.35%** | 49.72% | 97 | 169 | 133 | 14 (95%) | 83.33% / 83.33% | 1 (127 tokens) |
| 2 | groundtruth2 / transcription2 (2026-07-31) | 422 | 321 | 57.97% | **50.24%** | 46.55% | 93 | 110 | 9 | 25 (94%) | 71.43% / 76.92% | 0 |
| 3 | groundtruth3 / transcription3 (2026-07-31) | 844 | 631 | 43.74% | **38.51%** | 34.57% | 96 | 221 | 8 | 29 (96%) | 75.00% / 37.50% | 0 |
| 4 | groundtruth4 / transcription4 (2026-07-31) | 1181 | 1009 | 38.77% | **34.21%** | 33.48% | 216 | 180 | 8 | 13 (82%) | 100.00% / 62.96% | 1 (60 tokens) |
| 5 | groundtruth5 / transcription5 (2026-08-07) | 1225 | 1041 | 43.94% | **32.90%** | 29.14% | 171 | 208 | 24 | 16 (19%) | 89.47% / 85.00% | 0 |
| **Corpus** (micro) | all five | 4449 | 3743 | 48.40% | **39.18%** | 36.55% | 673 | 888 | 182 | 29 | n/a | 2 (187 tokens) |
| **Mean per call** (macro) | all five | | | 50.98% | **41.44%** | 38.69% | | | | | | |

Corpus CER = total errors / total reference tokens. The mean per call is higher because the short, worse calls
(1 and 2) weigh the same as the long ones.
S/D/I columns use the mapped variant (the `scored_variant` column in the CSV says which).

## Where the errors are

| Slice | Result (corpus, mapped) |
|---|---|
| Speaker | Agent (`CS`): 2879 ref tokens, error 35.60%, deleted 19.21%. Customer: 1570 ref tokens, error 45.73%, deleted 21.34% |
| English tokens | 199 ref tokens, **64.32%** missed (sub + del) vs 33.81% for Chinese characters |
| Numbers | 83 ref tokens, 28.92% missed |
| Call position | error rate per tenth of the call: 39%, 43%, 33%, 24%, 27%, 27%, 53%, 36%, 48%, **62%** |

- The customer side is worse than the agent side, and English words (names, brands, codes) are the weakest
  token type.
- The last tenth of the call is the worst. In calls 3 and 4 the final tenth is 70% and 67% wrong, and in
  call 4 the ninth tenth is 90%. The 53% in the seventh tenth is call 1's repeated passage (that call's
  seventh tenth is over 100% because of the insertions).

Per call (mapped):

| Call | Agent error / deleted | Customer error / deleted | English missed | Numbers missed | Last tenth error |
|---|---|---|---|---|---|
| 1 | 46.75% / 19.92% | 58.67% / 24.67% | 42.86% (21) | 15.79% (19) | 64.94% |
| 2 | 45.62% / 23.57% | 67.03% / 35.16% | 75.00% (16) | 16.67% (12) | 76.19% |
| 3 | 36.18% / 25.29% | 48.17% / 29.88% | 59.09% (22) | 75.00% (8) | 70.24% |
| 4 | 32.88% / 18.23% | 35.52% / 12.29% | 56.25% (96) | 40.74% (27) | 66.95% |
| 5 | 26.37% / 12.56% | 45.37% / 25.42% | 90.91% (44) | 11.76% (17) | 44.26% |

(English and number counts in brackets are reference tokens, so small calls are noisy.)

## Repeated passage impact

| Call | Repeated tokens | CER with repeat | CER without repeat | Impact |
|---|---|---|---|---|
| 1 | 127 (17.1% of hypothesis) | 51.35% | 37.19% | 14.16 pts |
| 4 | 60 (5.9% of hypothesis) | 34.21% | 31.08% | 3.13 pts |
| 2, 3, 5 | 0 | unchanged | unchanged | 0 |
| Corpus | 187 | 39.18% | 35.87% | 3.31 pts |

Ground truth is verified, so repeats are counted as model errors (included in the primary CER).
Call 1 is a clear loop (insertions 133 -> 18). Call 4's figure is lower confidence: removing the repeat
did not change insertions (8 -> 8), so the repeated text was mostly aligned onto reference words as
substitutions, and the 3.13 pts depends on how that alignment shifts.

## Main findings

| Finding | Evidence |
|---|---|
| Deletions are the largest error type | 888 of 1743 errors (51%) corpus-wide; 68% in call 3 |
| Transcripts are shorter than the ground truth | 3743 vs 4449 tokens (about 16% shorter); calls 2 and 3 about 25% shorter |
| The end of the call is the weakest part | Last tenth of the call is 62% wrong corpus-wide; the longest deleted run is 82-96% through the call in calls 1-4 |
| Customers are transcribed worse than agents | 45.73% vs 35.60% error |
| English code-switching is the weakest token type | 64% of English tokens missed |
| Loops can dominate a call | Call 1: a 127-token repeat costs 14.16 pts |
| Mandarin-style wording | Raw CER is 4.5-19 pts above mapped CER depending on the call |
| Entity recall is uneven | Call 3's real misses include a spoken phone number; call 4 precision 100% but recall 63% |

## Pairing checks

All five pairs matched by recording ID, and none was flagged: text overlap (share of reference character
pairs found in the transcript) was 0.38-0.63. Deliberately mismatched calls scored 0.06-0.22, so the script
warns below 0.30 (or when the transcript is under half or over 1.6 times the reference length) and
`--skip-suspect` leaves such pairs out. Pairs can also be forced with `--pairs`.

## Caveats

- Five calls only, so these are indicative, not a benchmark.
- The no-fillers column deletes particles on both sides (list in `docs/mappings.txt`).
- Call dates come from the recording filenames in the transcript headers; agent names are omitted.
- The ground truth is now normalized one speaker turn at a time (needed for the speaker split), so call 5's
  reference is one token longer than in the previous round (1224 -> 1225); other calls are unchanged.
- Speaker errors are attributed to the reference token's speaker; an insertion is attributed to the nearest
  reference token. Inline back-channels such as `（黃：係。）` count for the inner speaker.
- Entity scoring compares only the number part of ID-like tokens (letters + >=4 digits), so a prefix written
  separately or joined (`abcd 係 12345678` vs `abcd12345678`) no longer counts as a miss; the letters are
  covered by CER. IDs and spelled-out letters are also made spacing-insensitive in normalization.
