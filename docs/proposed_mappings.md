# Mappings proposal (HISTORY: A-E approved and applied, F skipped)

Status: this file records the draft that was approved. The live list is `docs/mappings.txt` (or
`--list-mappings`). Changes since approval: 來得切/嚟得切 and the typo spellings reconfium/reconfim
were removed as one-off to a single call.

Direction: Cantonese / English form -> the form the model tends to write.
Applied to BOTH sides under `--map-colloquial`, multi-char keys first.
"ref/hyp" = occurrences in the current groundtruth.docx / transcription.docx.

## A. Lexical swaps (low risk, recommended)
| Cantonese | -> | ref | hyp | Note |
|---|---|---|---|---|
| 跟住 | 接著 | 3 | 0 (hyp: 接著 x2) | "then / next" |
| 呢度 | 這裡 | 3 | 0 (hyp: 這裡 x5) | |
| 乜嘢 | 什麼 | 1 | 0 (hyp: 什麼 x1) | |
| 而家 | 現在 | 4 | 0 (hyp: 現在 x5) | |
| 仲 | 還 | 2 | 0 (hyp: 還 x4) | |
| 同埋 | 和 | 2 | 0 | |
| 直情 | 直接 | 1 | 0 | |
| 撳 | 按 | 1 | 0 | |
| 裡邊 | 裡面 | 2 | 0 (hyp: 裡面) | |
| 來得切 | 來得及 | 1 | 0 | GT spells the Cantonese sound |
| 係咪 | 是不是 | 7 | 0 (hyp: 是不是) | must run before 係->是 |
| 嘢 | 東西 | 4 | 0 | hyp may say 事情 instead |

## B. English code-switch (hyp translates English into Chinese)
| English | -> | Note |
|---|---|---|
| reply | 回覆 | |
| email | 電郵 | hyp also uses 郵件? check |
| check | 查 | |
| send | 發 | |
| reconfirm / reconfium / reconfim | 重新確認 | covers GT spellings |

## C. Context rules
| Rule | Example | Note |
|---|---|---|
| 同 -> 跟 only before 你/我/他 | 同你確認 -> 跟你確認 | 同埋 handled first |
| 呢一 -> 這一 | 呢一份 -> 這一份 | plain 呢 is NOT mapped (also a sentence particle) |

## D. Always-on variant fix
| 户 -> 戶 | GT has 客户 (variant 户), not caught by OpenCC |

## E. Fillers / particles to DELETE on both sides (policy decision)
嗯 哦 咦 阿 啊 呀 啦 囉 㗎 啫 吖 喇 喎 咯 嘛 (+ 好阿/好啊 -> 好)
- Pro: the model drops these (ref 4 嗯, 4 哦, 10 阿, 15 啦, 4 囉, 3 㗎, 1 咦...), so deleting them stops
  ~40 deletions from dominating the score.
- Con: hides real particle omissions. Suggest reporting CER both with and without (new `--drop-fillers` flag).

## F. Risky / needs your call
| Item | Issue |
|---|---|
| 返 (13 in ref, 0 in hyp) | verb suffix (做返/確認返) but also "回/返去"; dropping everywhere is blunt |
| 不該曬 (唔該晒) -> 麻煩 | hyp uses 麻煩 x5 / 謝謝 x1 for the same phrase; one-to-one map is wrong half the time. Option: fold 麻煩/謝謝/多謝/不該曬 into one class (loosens the metric) |
| 呢 -> 這 | 13 in ref but includes sentence-final 呢 |
| 條咪 -> 係咪 | GT typo; better fix the ground truth |

## Decision
Approved: A, B, C, D, E (as the `--drop-fillers` flag). Skipped: F.
