# Command-trace snapshot schema 1

ASCII unsigned decimals. Header:

```
H 1 run context phase errors pictures completions capacity first last words capture_size window_size
```

Then 300 `P picture poc type target flags intra` writer-history rows.

Then 11 window groups:

```
W picture poc type nwords nbytes inactive [site word]...
C b0 b1 ... b1391
```

Packed controls are named little-endian fields only: SPS (34) + PPS (63) +
scaling (1000) + one slice including pred-weight scalars/arrays (275) + decode
flags (8) = 1380, then 12 zero pad bytes to the 1392-byte slot. Reserved struct
bytes are not copied. Length mismatch invalidates the window. Slice metadata
records full size, relative offset, flags and `offset+data_byte_offset`.

Sites are `enum cmd_site` in `kernel/cmd-core.h`. Coded high/low address words are not a site.
