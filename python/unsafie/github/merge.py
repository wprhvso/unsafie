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
    base: bytes | None, ours: bytes | None, theirs: bytes | None
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


def _merge_lines(base: list[str], ours: list[str], theirs: list[str]) -> tuple[list[str], bool]:
    ours_ops = _ops(base, ours)
    theirs_ops = _ops(base, theirs)
    out: list[str] = []
    conflicted = False
    i = 0
    while i < len(base) + 1:
        a = ours_ops.get(i)
        b = theirs_ops.get(i)
        if a and b and a != b:
            conflicted = True
            out.append(MARK_OURS + "\n")
            out.extend(a[1])
            out.append(MARK_SPLIT + "\n")
            out.extend(b[1])
            out.append(MARK_THEIRS + "\n")
            i = max(a[0], b[0])
            continue
        chosen = a or b
        if chosen:
            out.extend(chosen[1])
            i = chosen[0]
            continue
        if i < len(base):
            out.append(base[i])
        i += 1
    return out, conflicted


def _ops(base: list[str], other: list[str]) -> dict[int, tuple[int, list[str]]]:
    ops: dict[int, tuple[int, list[str]]] = {}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, base, other, autojunk=False
    ).get_opcodes():
        if tag == "equal":
            continue
        ops[i1] = (i2, other[j1:j2])
    return ops


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
