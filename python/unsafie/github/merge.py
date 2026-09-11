import difflib
import logging
from dataclasses import dataclass, field

from unsafie.mime import is_text

logger = logging.getLogger(__name__)

MARK_OURS = "<<<<<<< yours"
MARK_SPLIT = "======="
MARK_THEIRS = ">>>>>>> remote"


@dataclass
class Result:
    merged: dict[str, bytes | None] = field(default_factory=dict)
    conflicts: list[str] = field(default_factory=list)
    taken_remote: list[str] = field(default_factory=list)
    kept_local: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.conflicts


def three_way(
    base: bytes | None, ours: bytes | None, theirs: bytes | None,
) -> tuple[bytes | None, bool]:
    if ours == theirs:
        return ours, False
    if ours == base:
        return theirs, False
    if theirs == base:
        return ours, False
    if ours is None or theirs is None:
        return ours if ours is not None else theirs, True
    if not (is_text(base) and is_text(ours) and is_text(theirs)):
        return ours, True
    merged, conflicted = _merge_lines(
        (base or b"").decode(errors="replace").splitlines(keepends=True),
        ours.decode(errors="replace").splitlines(keepends=True),
        theirs.decode(errors="replace").splitlines(keepends=True),
    )
    return "".join(merged).encode(), conflicted


@dataclass
class _Chunk:
    start: int
    end: int
    lines: list[str]


def _get_chunks(base: list[str], other: list[str]) -> list[_Chunk]:
    chunks = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, base, other, autojunk=False).get_opcodes():
        if tag != "equal":
            chunks.append(_Chunk(i1, i2, other[j1:j2]))
    return chunks


def _reconstruct_slice(base: list[str], chunks: list[_Chunk], start: int, end: int) -> list[str]:
    res = []
    curr = start
    for c in chunks:
        if c.start > curr:
            res.extend(base[curr:c.start])
        res.extend(c.lines)
        curr = max(curr, c.end)
    if curr < end:
        res.extend(base[curr:end])
    return res


def _merge_lines(base: list[str], ours: list[str], theirs: list[str]) -> tuple[list[str], bool]:
    ours_chunks = _get_chunks(base, ours)
    theirs_chunks = _get_chunks(base, theirs)
    out: list[str] = []
    conflicted = False

    idx_a = 0
    idx_b = 0
    curr_base = 0

    while idx_a < len(ours_chunks) or idx_b < len(theirs_chunks):
        if idx_a >= len(ours_chunks):
            b = theirs_chunks[idx_b]
            if b.start > curr_base:
                out.extend(base[curr_base:b.start])
            out.extend(b.lines)
            curr_base = b.end
            idx_b += 1
            continue

        if idx_b >= len(theirs_chunks):
            a = ours_chunks[idx_a]
            if a.start > curr_base:
                out.extend(base[curr_base:a.start])
            out.extend(a.lines)
            curr_base = a.end
            idx_a += 1
            continue

        a = ours_chunks[idx_a]
        b = theirs_chunks[idx_b]

        if a.start == b.start and a.end == b.end and a.lines == b.lines:
            if a.start > curr_base:
                out.extend(base[curr_base:a.start])
            out.extend(a.lines)
            curr_base = a.end
            idx_a += 1
            idx_b += 1
            continue

        if a.end < b.start or (a.end == b.start and (a.start != a.end or b.start != b.end)):
            if a.start > curr_base:
                out.extend(base[curr_base:a.start])
            out.extend(a.lines)
            curr_base = a.end
            idx_a += 1
            continue

        if b.end < a.start or (b.end == a.start and (b.start != b.end or a.start != a.end)):
            if b.start > curr_base:
                out.extend(base[curr_base:b.start])
            out.extend(b.lines)
            curr_base = b.end
            idx_b += 1
            continue

        conflicted = True
        c_start = min(a.start, b.start)
        c_end = max(a.end, b.end)
        a_cluster = [a]
        b_cluster = [b]
        idx_a += 1
        idx_b += 1

        while True:
            expanded = False
            if idx_a < len(ours_chunks) and ours_chunks[idx_a].start <= c_end:
                c_end = max(c_end, ours_chunks[idx_a].end)
                a_cluster.append(ours_chunks[idx_a])
                idx_a += 1
                expanded = True
            if idx_b < len(theirs_chunks) and theirs_chunks[idx_b].start <= c_end:
                c_end = max(c_end, theirs_chunks[idx_b].end)
                b_cluster.append(theirs_chunks[idx_b])
                idx_b += 1
                expanded = True
            if not expanded:
                break

        if c_start > curr_base:
            out.extend(base[curr_base:c_start])

        ours_content = _reconstruct_slice(base, a_cluster, c_start, c_end)
        theirs_content = _reconstruct_slice(base, b_cluster, c_start, c_end)

        if ours_content == theirs_content:
            out.extend(ours_content)
        else:
            out.append(MARK_OURS + "\n")
            out.extend(ours_content)
            out.append(MARK_SPLIT + "\n")
            out.extend(theirs_content)
            out.append(MARK_THEIRS + "\n")

        curr_base = c_end

    if curr_base < len(base):
        out.extend(base[curr_base:])

    return out, conflicted


def rebase(
    base_files: dict[str, bytes | None],
    ours: dict[str, bytes | None],
    theirs: dict[str, bytes | None],
) -> Result:
    result = Result()
    for path in sorted(set(ours) | set(theirs)):
        base = base_files.get(path)
        mine = ours.get(path, base)
        remote = theirs.get(path, base)
        if path not in ours:
            result.merged[path] = remote
            result.taken_remote.append(path)
            continue
        if path not in theirs:
            result.merged[path] = mine
            result.kept_local.append(path)
            continue
        merged, conflicted = three_way(base, mine, remote)
        result.merged[path] = merged
        if conflicted:
            result.conflicts.append(path)
    return result
