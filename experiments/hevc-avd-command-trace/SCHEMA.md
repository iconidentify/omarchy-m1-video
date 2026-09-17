# Command snapshot schema 2

ASCII canonical unsigned decimals; signed POCs use u32 two's complement.
The command schema is separate from the accepted reference schema 2.

```text
H 2 run context phase errors pictures completions capacity first last words capture_size window_size
P picture poc type target flags intra
W picture poc type nwords nbytes inactive decomp revision quirks bytesperline [site word]...
C b0 b1 ... b1391
```

Exactly one header, 300 ordered P rows (1–300), and 11 W/C pairs (24–34).
Header constants: phase=4, errors=0, pictures=completions=300, capacity=2048,
first=24, last=34, words=1024, capture_size=90824, window_size=7596.
A nonzero expected run is mandatory; context must match the paired reference trace.

`kernel/control-layout.inc` is the complete named little-endian wire field order:
SPS34 + PPS63 + scaling1000 + slice/pred-weights275 + decode flags8 = 1380 bytes,
followed by 12 required zero wire bytes. Native reserved bytes are never copied.
Signed scalar fields are explicitly typed; signed weight arrays retain their byte
encodings. The source oracle reconstructs their actual signed C types.

Sites 1–32 are `enum cmd_site` in `kernel/cmd-core.h`. Every selected word is
ordered; repeated sites are meaningful (including interior array words). Site31
has four consecutive words: size, relative offset, coded flags, and relative
coded offset including `data_byte_offset`. No coded address word is exported.
Device context needed for header/stride construction is explicitly recorded.

Inactive is a bitset with only bit19 (scaling disabled) and bit27 (I-slice weights
skipped). Disabled scaling still emits its zero marker. Unweighted P/B emits a
real default weight header and does **not** set skipped-I. Missing words, controls,
histories or device context are errors, never inferred zeros.

The strict parser checks wire/domain/job structure; `oracle.py check` additionally
requires the accepted same-run reference history/validator and compares every
selected word against the pinned C. A syntactically valid snapshot alone is not
accepted command evidence. Any discrepancy, reference finding or malformed input
returns nonzero. There is no caller-supplied expected-word shortcut.
