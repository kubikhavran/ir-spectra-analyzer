# SPA Metadata Capability Matrix

**Source files used:**
- `0min-1-97C.SPA` — Nicolet iS10, 97°C sample, 0 min timepoint
- `30min-1-97C.SPA` — Nicolet iS10, 97°C sample, 30 min timepoint
- `113361_2-22.SPA` — Nicolet iS10, 113°C session

**Instrument:** Thermo Fisher Nicolet iS10 FT-IR spectrometer  
**Public source:** github.com/pricebenjamin/SPA-file-reader  
**Date of analysis:** 2026-04-02  
**Status:** ⚠ TEMPORARY FIXTURES — public sample data only. Re-validate once real
production .SPA files from your own instrument are available.

---

## Binary format — confirmed structure

```
Byte range    Content
-----------   -------
0 – 17        Magic: "Spectral Data File" (always this string in OMNIC files)
18 – 19       CR LF
20 – 29       null padding
30 – 284      User title / sample name (255 bytes, latin-1, null-terminated)
              NOTE: may contain timestamp instead of name depending on OMNIC version
285 – 287     unknown (always 00 in observed files)
288 – 303     Section directory entry 0 — type=1, invalid offset/size (skip)
304 – N       Section directory entries (16 bytes each):
                [0-1]  type (uint16 LE)
                [2-5]  data offset from file start (uint32 LE)
                [6-9]  data block size in bytes (uint32 LE)
                [10-15] unknown / padding (zeros)
              Table ends when type == 0
```

**Fixed-offset params (Nicolet iS10 specific):**
- Offset 564: n_points (uint32 LE) — same as type-2 block [+4]
- Offset 576: wn_max (float32 LE) — same as type-2 block [+16]
- Offset 580: wn_min (float32 LE) — same as type-2 block [+20]

These fixed offsets exist because the type-2 block is always at offset 560 in these files.
**Do not rely on hardcoded offsets for other instruments.**

---

## Known section types

| Type | Hex    | Name                    | Description                                          |
|------|--------|-------------------------|------------------------------------------------------|
| 1    | 0x0001 | File header             | Entry 0 at offset 288; has non-standard offset/size  |
| 2    | 0x0002 | Spectral parameters     | n_pts@+4, wn_max@+16, wn_min@+20 (f32 LE each)     |
| 3    | 0x0003 | Intensity data          | n_pts × float32 LE; primary spectral data            |
| 27   | 0x001B | Acquisition history     | Plain-text acquisition log (latin-1, CRLF)           |
| 100  | 0x0064 | Unknown (footer?)       | 24 bytes near end of file                            |
| 101  | 0x0065 | Unknown                 | 24 bytes                                             |
| 102  | 0x0066 | Unknown (spectrum?)     | 270336 bytes — may be background or interferogram    |
| 103  | 0x0067 | Unknown (spectrum?)     | 270336 bytes — may be background or interferogram    |
| 105  | 0x0069 | Unknown (thumbnail?)    | 12 bytes                                             |
| 106  | 0x006A | Unknown                 | 56 bytes                                             |
| 130  | 0x0082 | Unknown (×3 entries)    | 12, 724, 932 bytes — possibly background metadata   |
| 384  | 0x0180 | Unknown                 | 128 bytes                                            |

Types 102/103 have the same size (270336 bytes) across all observed files.
These may be sample/background interferograms. **Not yet parsed or exposed.**

---

## Acquisition history text (type-27 block)

Full content from `0min-1-97C.SPA`:
```
Collect Sample
	 Background collected on Thu Feb 23 16:35:07 2017 (GMT-08:00)
	 Final format:	%Transmittance
	 Resolution:	 0.500 from 649.9812 to 3999.9907
	 Validation wheel: 0
	 Attenuation screen wheel: None
	 Bench Serial Number:AKX1300131
	 Sample compartment: Main
```

Fields parseable via regex from type-27 text:
- **acquired_at_str** — "Thu Feb 23 16:35:07 2017" (not yet parsed into `datetime`)
- **y_unit_str** — "%Transmittance" → maps to `SpectralUnit.TRANSMITTANCE`
- **resolution_cm** — "0.500" (cm⁻¹)
- **instrument_serial** — "AKX1300131"
- **wn_range** — "649.9812 to 3999.9907" (redundant with fixed-offset params)

---

## Metadata capability matrix

| Field              | Our binary reader            | Reference parsers             | Confidence   | Notes                                                    |
|--------------------|------------------------------|-------------------------------|--------------|----------------------------------------------------------|
| title              | bytes 30-284 (latin-1)       | bytes 30-284                  | CONFIRMED    | May be sample name or timestamp depending on OMNIC version |
| n_points           | fixed offset 564 (u32)       | fixed offset 564 (u32)        | CONFIRMED    | Always at offset 564 in observed files                   |
| first_wavenumber   | fixed offset 580 (f32)       | fixed offset 580 (f32)        | CONFIRMED    | wn_min; linspace endpoint                                |
| last_wavenumber    | fixed offset 576 (f32)       | fixed offset 576 (f32)        | CONFIRMED    | wn_max; linspace startpoint                              |
| y_unit             | HARDCODED ABSORBANCE         | detected from type-27 text    | LOW / WRONG  | Real Nicolet files are %Transmittance, not Absorbance    |
| x_unit             | HARDCODED WAVENUMBER         | detected from type-27 text    | MEDIUM       | NIR range possible; step size also available in type-27  |
| acquired_at        | NOT EXTRACTED (in extra_meta)| not extracted                 | DEFERRED     | Available in type-27 text; needs datetime parsing        |
| resolution_cm      | NOT EXTRACTED (in extra_meta)| not extracted                 | DEFERRED     | Available in type-27 text; "0.500" in observed files     |
| instrument_serial  | NOT EXTRACTED (in extra_meta)| not extracted                 | DEFERRED     | Available in type-27 text; "AKX1300131" in observed files |
| comments           | NOT EXTRACTED                | not extracted                 | UNKNOWN      | May be part of type-27 text                              |
| extra_metadata     | omnic_format, wn_max/min,    | —                             | CONFIRMED    | Dict populated; provenance fields present                |
|                    | n_points, data_offset        |                               |              |                                                          |
| sample_compartment | NOT EXTRACTED                | not extracted                 | DEFERRED     | Available in type-27 text                                |
| background_date    | NOT EXTRACTED                | not extracted                 | DEFERRED     | Available in type-27 text ("Background collected on...") |

---

## Honest limitations

### What the binary parser CAN reliably extract (confirmed on these fixtures)
- Wavenumber axis (first/last/n_points → linspace)
- Float32 intensity array
- Sample title / user-entered name
- omnic_format detection flag
- Wavenumber range provenance (wn_max, wn_min stored in extra_metadata)

### What is NOT yet extracted (but IS in the file)
- `acquired_at`: available in type-27 text as human-readable string; needs `datetime.strptime`
- `y_unit`: hardcoded as ABSORBANCE but real files are %Transmittance — **this is a known bug**
- `resolution_cm`: in type-27 text
- `instrument_serial`: in type-27 text
- Types 102/103 content (background/interferogram data?)

### What CANNOT be extracted from binary (not in file)
- **Manually added OMNIC peaks** — not stored in .SPA; peaks are OMNIC application state
- **OMNIC annotations** — not stored in .SPA
- **Saved interpretations / vibrational assignments** — not in .SPA; must be stored in our own DB
- **Baseline history** — not confirmed present in section types observed
- **Labeled peaks** — not stored in .SPA

### What is UNKNOWN (not yet determined)
- Whether types 102/103 are sample+background or two scans
- Whether section directory entry 0 (type=1, invalid offset) is universal or instrument-specific
- Whether the fixed offset 560 for the type-2 block is universal or Nicolet iS10 specific
- Whether the "title" field (bytes 30-284) is always the sample name or sometimes a timestamp

---

## Important note on y_unit

All observed files use `%Transmittance` (from type-27 text: `Final format: %Transmittance`).
The current parser **hardcodes `SpectralUnit.ABSORBANCE`** — this is incorrect for these files.

**Impact:** The viewer will label the Y axis "Absorbance" but display transmittance values
(typically 44–108% range). This is visible in the data: intensities ~44–108 are percent
transmittance, not absorbance (which is typically 0–3).

**Planned fix:** Parse type-27 text in `SPABinaryReader._parse_omnic_format()` and set
`y_unit` correctly. Also extract `acquired_at` and `resolution_cm` at the same time.

---

## What must be re-tested once real production .SPA files are available

1. **Section directory offset** — is it always 288? Confirm on your instrument.
2. **Type-2 block offset** — is it always at 560? Verify with your files.
3. **Title field** — does your OMNIC save sample name in bytes 30-284? Or somewhere else?
4. **y_unit** — does your instrument produce Absorbance, Transmittance, or both?
5. **Wavenumber range** — what is your instrument's actual range and resolution?
6. **Type-27 text format** — is the acquisition history text format the same?
7. **Types 102/103** — what are they? Worth parsing?
8. **Manually added peaks in OMNIC** — where are they stored, if at all?
9. **n_points at fixed offset 564** — confirm this holds for your instrument.

---

## Architecture recommendation

The current dual-mode parser design is sound:
- **OMNIC magic detection** (`"Spectral Data File"`) enables format identification without fragile heuristics
- **Fixed offsets** (564/576/580) work for Nicolet iS10; dynamic type-2 block parsing would be more robust
- **type-27 text block** is the richest metadata source; parsing it would give `acquired_at`, `y_unit`, `resolution_cm`, `instrument_serial`
- **extra_metadata dict** is the right place to accumulate fields not yet in the formal model

**Next parser milestone:** Extract type-27 text → populate `acquired_at`, `y_unit`, and `resolution_cm` in the Spectrum model. This is low-risk and high value.
