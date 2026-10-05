"""Scoring of carved output against ground truth. Counts are integers (exact aggregation)."""

import hashlib
import math
from dataclasses import dataclass, field


@dataclass
class Carved:
    """One carved clip (or parsed clip) as seen by the scorer."""

    codec: str
    extents: list[list[int]]
    reassembled: bool = False
    decode_status: str = "not_run"  # ok | decode_errors | export_failed | not_run
    recorded_sha256: str = ""
    mp4_ok: bool | None = None  # None when no MP4 was produced/checked


@dataclass
class Counts:
    images: int = 0
    # clip level
    truth_expected: int = 0  # truth clips with >= 1 recoverable frame
    truth_detected: int = 0  # >= 50% of recoverable frames recovered
    exact_eligible: int = 0  # truth clips fully intact and expected
    exact: int = 0  # carved extents == truth extents
    carved: int = 0
    tp: int = 0  # carved clips attributable (>= 50% of bytes) to an expected truth clip
    mixed: int = 0  # carved clips drawing >= 10% of bytes from two or more truth clips
    # frame level
    frames_recoverable: int = 0
    frames_recovered: int = 0  # recoverable frames inside carved extents
    frames_covered_any: int = 0  # truth VCL NALs inside carved extents (damaged ones too)
    # bytes
    carved_bytes: int = 0
    extra_bytes: int = 0  # carved bytes not inside any truth NAL
    # status / integrity
    decode_ok: int = 0
    decode_errors: int = 0
    export_failed: int = 0
    hash_checked: int = 0
    hash_ok: int = 0
    # negatives
    neg_clips: int = 0
    neg_decode_ok: int = 0
    # reassembly
    join_wrong_candidates: int = 0
    join_wrong_accepted: int = 0
    join_right_candidates: int = 0
    join_right_accepted: int = 0
    failures: list = field(default_factory=list)

    def add(self, o: "Counts") -> None:
        for k, v in o.__dict__.items():
            if k == "failures":
                self.failures += v
            else:
                setattr(self, k, getattr(self, k) + v)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round(max(0.0, (c - m) / d), 4), round(min(1.0, (c + m) / d), 4)


def rate(k: int, n: int) -> dict:
    return {"k": k, "n": n, "rate": None if n == 0 else round(k / n, 4), "ci95": wilson(k, n)}


def _same_extents(a: list[list[int]], b: list[list[int]], img: bytes) -> bool:
    """Equal up to zero-only differences at the boundaries (a zero byte in front of a start code
    is ambiguous: trailing zero of the previous data or leading zero_byte of this one)."""
    a, b = _merge_zero_gaps(_norm(a), img), _merge_zero_gaps(_norm(b), img)
    if len(a) != len(b):
        return False
    return all(
        not any(img[min(x[0], y[0]) : max(x[0], y[0])])
        and not any(img[min(x[1], y[1]) : max(x[1], y[1])])
        for x, y in zip(a, b, strict=True)
    )


def _merge_zero_gaps(ext: list[list[int]], img: bytes) -> list[list[int]]:
    out: list[list[int]] = []
    for s, e in ext:
        if out and not any(img[out[-1][1] : s]):
            out[-1][1] = e
        else:
            out.append([s, e])
    return out


def _overlap(a: list[list[int]], b: list[list[int]]) -> int:
    tot = 0
    for s1, e1 in a:
        for s2, e2 in b:
            tot += max(0, min(e1, e2) - max(s1, s2))
    return tot


def _norm(ext: list[list[int]]) -> list[list[int]]:
    out: list[list[int]] = []
    for s, e in sorted(ext):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def score_image(truth: dict, carved: list[Carved], image: bytes, trial: str, join_log=()) -> Counts:
    c = Counts(images=1)
    clips = truth["clips"]
    t_ext = {t["id"]: _norm([[p[0], p[1]] for p in t["pieces"]]) for t in clips}
    expected = {t["id"] for t in clips if t["expected"] == "recover"}
    c.carved = len(carved)

    # per carved clip: attribution, hash integrity, status
    for cl in carved:
        ext = _norm(cl.extents)
        size = sum(e - s for s, e in ext)
        c.carved_bytes += size
        ov = {tid: _overlap(ext, te) for tid, te in t_ext.items()}
        best = (
            max(ov, key=lambda t: (ov[t], t in expected)) if ov else None
        )  # ties: expected clip wins
        attributable = best is not None and size and ov[best] >= 0.5 * size and best in expected
        c.tp += int(bool(attributable))
        if sum(1 for v in ov.values() if size and v >= 0.1 * size) >= 2:
            c.mixed += 1
        if not attributable:
            c.failures.append(
                {
                    "trial": trial,
                    "kind": "false_positive_clip",
                    "extents": ext[:4],
                    "decode": cl.decode_status,
                }
            )
        c.decode_ok += cl.decode_status == "ok"
        c.decode_errors += cl.decode_status == "decode_errors"
        c.export_failed += cl.decode_status == "export_failed"
        if cl.recorded_sha256:
            h = hashlib.sha256()
            for s, e in cl.extents:
                h.update(image[s:e])
            c.hash_checked += 1
            c.hash_ok += int(h.hexdigest() == cl.recorded_sha256 and cl.mp4_ok is not False)

    covered = _norm([x for cl in carved for x in cl.extents])

    def inside(off: int, ln: int) -> bool:
        return any(s <= off and off + ln <= e for s, e in covered)

    nal_ranges = []
    for t in clips:
        rec = [n for n in t["nals"] if n["vcl"] and n["recoverable"]]
        got = sum(1 for n in rec if inside(n["img_off"], n["len"]))
        c.frames_recoverable += len(rec)
        c.frames_recovered += got
        c.frames_covered_any += sum(
            1
            for n in t["nals"]
            if n["vcl"] and n["img_off"] is not None and inside(n["img_off"], n["len"])
        )
        nal_ranges += [
            [n["img_off"], n["img_off"] + n["len"]] for n in t["nals"] if n["img_off"] is not None
        ]
        if t["id"] in expected and rec:
            c.truth_expected += 1
            detected = got >= 0.5 * len(rec)
            c.truth_detected += int(detected)
            if not detected:
                c.failures.append(
                    {
                        "trial": trial,
                        "kind": "missed_clip",
                        "clip": t["id"],
                        "recovered": got,
                        "recoverable": len(rec),
                    }
                )
        intact = all(n["intact"] for n in t["nals"])
        if t["id"] in expected and intact:
            c.exact_eligible += 1
            c.exact += int(any(_same_extents(cl.extents, t_ext[t["id"]], image) for cl in carved))
    truth_nal = _norm(nal_ranges)
    c.extra_bytes = sum(e - s for s, e in covered) - _overlap(covered, truth_nal)

    # negatives (clips expected to be destroyed or absent)
    destroyed = {t["id"] for t in clips if t["expected"] == "none"}
    if not expected and not destroyed:  # pure negative image
        c.neg_clips = len(carved)
        c.neg_decode_ok = sum(1 for cl in carved if cl.decode_status == "ok")

    # fragment reassembler decisions, classified against ground truth
    for prev_end, start, accepted in join_log:
        right = _is_right_join(truth, prev_end, start, image)
        if right:
            c.join_right_candidates += 1
            c.join_right_accepted += int(accepted)
        else:
            c.join_wrong_candidates += 1
            c.join_wrong_accepted += int(accepted)
    return c


def _stream_off(truth: dict, img_off: int):
    for t in truth["clips"]:
        for s, e, ss in t["pieces"]:
            if s <= img_off < e:
                return t["id"], ss + (img_off - s)
    return None


def _is_right_join(truth: dict, prev_end: int, start: int, image: bytes = b"") -> bool:
    """True when the candidate NAL is, in the source stream, the byte-adjacent successor of the
    clip's last NAL (source streams carry no padding between NAL units)."""
    a = _stream_off(truth, prev_end - 1)
    b = _stream_off(truth, start)
    while b is None and image and start < len(image) - 1 and image[start] == 0:
        start += 1  # carved start may include one zero byte in front of a 3-byte start code
        b = _stream_off(truth, start)
    return a is not None and b is not None and a[0] == b[0] and b[1] == a[1] + 1
