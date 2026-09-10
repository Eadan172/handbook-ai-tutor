from __future__ import annotations


def make_text_pdf(text: str, *, title: str = "Lesson") -> bytes:
    """Build a tiny valid PDF-1.4 with Helvetica text (no extra dependencies)."""
    safe = "".join(ch if 32 <= ord(ch) < 127 and ch not in "()\\" else " " for ch in text)
    if len(safe) > 400:
        safe = safe[:400]
    lines = []
    words = safe.split()
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if len(trial) > 80:
            if current:
                lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    if not lines:
        lines = ["(empty)"]

    # One Tj per line, 16pt leading.
    ops = ["BT", "/F1 12 Tf", "72 740 Td"]
    for i, line in enumerate(lines):
        if i:
            ops.append("0 -16 Td")
        ops.append(f"({line}) Tj")
    ops.append("ET")
    stream = "\n".join(ops).encode("ascii")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Title (%s) /Producer (Handbook AI Tutor) >>" % title.encode("ascii", "replace"),
    ]

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    xref_start = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R /Info 6 0 R >>\n"
        f"startxref\n{xref_start}\n%%EOF\n"
    ).encode("ascii")
    return bytes(out)
