from __future__ import annotations

import re

from claimlens.adapters.ports import IndexedChunk

_HEAD = re.compile(r"^##\s+Clause\s+(\d+(?:\.\d+)?)\s+(.+?)\s*$", re.M)


def chunk_policy_wording(markdown: str, *, tenant_id: str, policy_id: str) -> list[IndexedChunk]:
    """Split on ``## Clause X.Y Title`` headings so every chunk is one citable clause."""
    matches = list(_HEAD.finditer(markdown))
    chunks: list[IndexedChunk] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        body = markdown[m.end() : end].strip()
        chunks.append(
            IndexedChunk(
                chunk_id=f"{policy_id}:{m[1]}",
                clause=m[1],
                title=m[2],
                text=f"Clause {m[1]} {m[2]}. {body}",
                policy_id=policy_id,
                tenant_id=tenant_id,
            )
        )
    return chunks
