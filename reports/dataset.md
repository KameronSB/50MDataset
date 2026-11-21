# Historical English corpus · full-b5da4f869f5b1869

full-b5da4f869f5b1869  |  49,802,774 characters, 140 documents  |  integrity_valid=True  targets_met=True

Requested 50,000,000 characters. Accepted band 49,000,000–51,000,000. Nominal shortfall 197,226. The selection contains 98 identified principal authors.

| Category | Characters | Target | Actual | Difference |
|---|---:|---:|---:|---:|
| essays_philosophy_economics_society | 3,096,128 | 6.00% | 6.22% | +0.22 pp |
| fiction | 15,175,863 | 30.00% | 30.47% | +0.47 pp |
| history | 8,131,644 | 16.00% | 16.33% | +0.33 pp |
| letters_diaries_memoirs | 6,961,995 | 14.00% | 13.98% | -0.02 pp |
| practical_technical | 2,290,713 | 4.00% | 4.60% | +0.60 pp |
| science_natural_history | 9,085,252 | 20.00% | 18.24% | -1.76 pp |
| travel_exploration | 5,061,179 | 10.00% | 10.16% | +0.16 pp |
| AU | 4,929,867 | 10.00% | 9.90% | -0.10 pp |
| CA | 5,854,224 | 12.00% | 11.75% | -0.25 pp |
| NZ | 4,104,317 | 8.00% | 8.24% | +0.24 pp |
| UK | 19,983,911 | 40.00% | 40.13% | +0.13 pp |
| US | 14,930,455 | 30.00% | 29.98% | -0.02 pp |
| train | 44,741,185 | 90.00% | 89.84% | -0.16 pp |
| validation | 2,528,648 | 5.00% | 5.08% | +0.08 pp |
| test | 2,532,941 | 5.00% | 5.09% | +0.09 pp |

## Candidate decisions

- review — 1,693
- reserve — 164
- selected — 140
- duplicate — 6
- excluded — 7
- unavailable — 3

## Historical periods by character count

- 1800–1849 — 6,082,484
- 1850–1899 — 14,044,707
- 1900–1945 — 29,675,583

## Decades by character count

- 1810s — 236,874
- 1820s — 487,431
- 1830s — 4,350,418
- 1840s — 1,007,761
- 1850s — 1,158,869
- 1860s — 2,248,181
- 1870s — 3,138,990
- 1880s — 2,409,423
- 1890s — 5,089,244
- 1900s — 9,599,971
- 1910s — 13,742,655
- 1920s — 6,332,957

## Sources by character count

- Project Gutenberg — 49,360,760
- Project Gutenberg Australia — 442,014

## Review and coverage

- 1399 candidates — Item record has not been checked in the bounded acquisition run
- 193 candidates — evidence review incomplete
- 182 candidates — Previously acquired or inspected item no longer matches the current bibliographic evidence
- 56 candidates — text contributor term unresolved
- 29 candidates — unreviewed textual contributors
- Project Gutenberg — 2,011 candidate records, 505 retained raw documents and 5 item acquisition errors in this build.
- Project Gutenberg Australia — 1 candidate records, 1 retained raw documents and 0 item acquisition errors in this build.
- Faded Page — Linked TXT returned the record HTML on the direct automated request. Edition and text boundaries unresolved.
- DigitalNZ — Developer landing page returned an empty 202 response in the access check. No API integration.
- NZETC — Web archive collection with item-specific permissions. No eligible text route verified.
- 5 acquisition errors — no linked plain text or generated HTML in the mirror directory

## Partition composition

| Partition | Documents | UK | US | CA | AU | NZ | Export separator characters |
|---|---:|---:|---:|---:|---:|---:|---:|
| train | 125 | 40.81% | 31.38% | 13.08% | 7.77% | 6.96% | 248 |
| validation | 8 | 42.29% | 16.17% | 0.00% | 41.53% | 0.00% | 14 |
| test | 7 | 25.89% | 19.09% | 0.00% | 15.88% | 39.15% | 12 |

The largest author group is Montgomery, L. M. (Lucy Maud), 1874-1942; Claus, M. A. (May Austin), 1882-1976 [Illustrator]; Claus, William A. J. (William Anton Joseph), 1862-1926 [Illustrator] with 3,727,574 characters (7.48%).

The release statistics include per-partition composition, author concentration, input hashes and export separator counts. The preparation guide documents the cleaning, eligibility and overlap rules. [Release statistics](../data/statistics.json) · [Preparation guide](../docs/preparation.md)

Rebuild against the retained pool with the following command.

```console
uv run python -m llm_v2_dataset build --config config.toml --offline
```
