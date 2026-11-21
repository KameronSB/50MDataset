# Historical English dataset for language model training

This repository includes **49,802,774 cleaned characters across 140 documents by 98 authors**. The corpus contains English writing first published from 1800 to 1945. A standard Git clone downloads the three splits under `data/`. You can start training as soon as the clone finishes.

| File | Documents | Characters | Use |
|---|---:|---:|---|
| [data/train.jsonl](data/train.jsonl) | 125 | 44,741,185 | Fit your tokenizer and train your model. |
| [data/validation.jsonl](data/validation.jsonl) | 8 | 2,528,648 | Compare checkpoints and tune hyperparameters. |
| [data/test.jsonl](data/test.jsonl) | 7 | 2,532,941 | Evaluate the final model after choosing its settings. |

## Load the text

Each UTF-8 JSONL line contains one complete document. Read `text` as the tokenizer input and use `document_id` to identify the work. This example runs from the repository root using Python's standard library.

```python
import json
from pathlib import Path


def documents(path):
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            yield record["document_id"], record["text"]


document_id, text = next(documents("data/train.jsonl"))
print(document_id, len(text))
```

In your PyTorch training code, loop over `documents("data/train.jsonl")` and encode each document with your tokenizer. Use the same trained tokenizer for validation and test. Whole works and known principal authors stay within a single split. The manifest lists each document's assignment. [Split manifest](data/split_manifest.csv)

## Sources and reproducibility

The source texts come from Project Gutenberg and Project Gutenberg Australia. Each work retains its source-specific rights status. The source list gives the title, author, date, archive record and rights evidence for each selected work. [Sources by document](reports/sources.csv) · [Dataset report](reports/dataset.md)

The release ID is `full-b5da4f869f5b1869`. Record the Git commit with your experiment to identify the exact files you used. The statistics include a SHA-256 checksum for each split. [Release statistics](data/statistics.json)

To change the corpus or reproduce the archive pipeline, see the [dataset preparation guide](docs/preparation.md).
