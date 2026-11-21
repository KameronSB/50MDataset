# Historical English corpus · trial-10-14198ee31c0366cc

trial-10-14198ee31c0366cc  |  4,456,834 characters, 10 documents  |  integrity_valid=True  targets_met=False

Requested 50,000,000 characters. Accepted band 49,000,000–51,000,000. Nominal shortfall 45,543,166. The selection contains 10 identified principal authors.

| Category | Characters | Target | Actual | Difference |
|---|---:|---:|---:|---:|
| essays_philosophy_economics_society | 228,487 | 6.00% | 5.13% | -0.87 pp |
| fiction | 2,350,380 | 30.00% | 52.74% | +22.74 pp |
| history | 0 | 16.00% | 0.00% | -16.00 pp |
| letters_diaries_memoirs | 635,284 | 14.00% | 14.25% | +0.25 pp |
| practical_technical | 366,631 | 4.00% | 8.23% | +4.23 pp |
| science_natural_history | 678,901 | 20.00% | 15.23% | -4.77 pp |
| travel_exploration | 197,151 | 10.00% | 4.42% | -5.58 pp |
| AU | 442,014 | 10.00% | 9.92% | -0.08 pp |
| CA | 1,595,682 | 12.00% | 35.80% | +23.80 pp |
| NZ | 236,887 | 8.00% | 5.32% | -2.68 pp |
| UK | 983,185 | 40.00% | 22.06% | -17.94 pp |
| US | 1,199,066 | 30.00% | 26.90% | -3.10 pp |
| train | 3,854,387 | 90.00% | 86.48% | -3.52 pp |
| validation | 322,247 | 5.00% | 7.23% | +2.23 pp |
| test | 280,200 | 5.00% | 6.29% | +1.29 pp |

## Candidate decisions

- review — 1,818
- selected — 10
- excluded — 7

## Historical periods by character count

- 1850–1899 — 1,984,820
- 1900–1945 — 2,472,014

## Decades by character count

- 1870s — 1,273,435
- 1880s — 474,498
- 1890s — 236,887
- 1900s — 799,598
- 1910s — 1,672,416

## Sources by character count

- Project Gutenberg — 4,014,820
- Project Gutenberg Australia — 442,014

## Review and coverage

- 1812 candidates — Item record has not been checked in the bounded acquisition run
- 5 candidates — evidence review incomplete
- 4 candidates — Previously acquired or inspected item no longer matches the current bibliographic evidence
- 1 candidates — English catalogue evidence required
- 1 candidates — English original or dated translator evidence required
- Project Gutenberg — 1,833 candidate records, 13 retained raw documents and 0 item acquisition errors in this build.
- Project Gutenberg Australia — 1 candidate records, 1 retained raw documents and 0 item acquisition errors in this build.
- Faded Page — Linked TXT returned the record HTML on the direct automated request. Edition and text boundaries unresolved.
- DigitalNZ — Developer landing page returned an empty 202 response in the access check. No API integration.
- NZETC — Web archive collection with item-specific permissions. No eligible text route verified.

## Partition composition

| Partition | Documents | UK | US | CA | AU | NZ | Export separator characters |
|---|---:|---:|---:|---:|---:|---:|---:|
| train | 8 | 18.24% | 31.11% | 33.04% | 11.47% | 6.15% | 14 |
| validation | 1 | 0.00% | 0.00% | 100.00% | 0.00% | 0.00% | 0 |
| test | 1 | 100.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0 |

The largest author group is Kirby, William, 1817-1906 with 1,273,435 characters (28.57%).

The trial statistics include per-partition composition, author concentration, input hashes and export separator counts. The preparation guide documents the cleaning, eligibility and overlap rules. [Trial statistics](statistics.json) · [Preparation guide](../../docs/preparation.md)

Rebuild against the retained pool with the following command.

```console
uv run python -m llm_v2_dataset build --config config.toml --offline --max-documents 10
```
