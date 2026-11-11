import glob
import os
import re
from typing import Any

from app.ingest import VectorStoreProtocol, ingest_document
from app.targets import DeduplicationStoreProtocol


def parse_pattern_markdown(filepath: str) -> dict[str, Any]:
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    meta: dict[str, Any] = {
        "source_url": f"file://{os.path.abspath(filepath)}",
        "category": "architecture_spec",
    }

    # Extract metadata fields from header block
    cat_match = re.search(r"-\s*\*\*분류\*\*:\s*`?([^`\n]+)`?", content)
    domain_match = re.search(r"-\s*\*\*도메인\*\*:\s*`?([^`\n]+)`?", content)
    target_match = re.search(r"-\s*\*\*주제\*\*:\s*`?([^`\n]+)`?", content)
    title_match = re.search(r"-\s*\*\*제목\*\*:\s*`?([^`\n]+)`?", content)
    priority_match = re.search(r"-\s*\*\*우선순위\*\*:\s*`?([^`\n]+)`?", content)

    if cat_match:
        meta["category"] = cat_match.group(1).strip()
    if domain_match:
        meta["domain"] = domain_match.group(1).strip()
    if target_match:
        meta["target_name"] = target_match.group(1).strip()
    if title_match:
        meta["title"] = title_match.group(1).strip()
    if priority_match:
        meta["priority"] = priority_match.group(1).strip()

    return {
        "text": content,
        "metadata": meta,
    }


def ingest_all_patterns(
    patterns_dir: str = "patterns",
    *,
    vector_store: VectorStoreProtocol | None = None,
    dedup_store: DeduplicationStoreProtocol | None = None,
) -> int:
    search_path = os.path.join(patterns_dir, "**", "*.md")
    files = glob.glob(search_path, recursive=True)
    total_chunks = 0

    for fpath in files:
        parsed = parse_pattern_markdown(fpath)
        chunks = ingest_document(
            text=parsed["text"],
            metadata=parsed["metadata"],
            vector_store=vector_store,
            dedup_store=dedup_store,
            inject_header=True,
        )
        total_chunks += chunks

    return total_chunks


if __name__ == "__main__":
    print(f"Indexing patterns from patterns/...")
    count = ingest_all_patterns("patterns")
    print(f"Pattern indexing completed: {count} chunks indexed.")
