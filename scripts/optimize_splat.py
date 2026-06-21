"""Create a browser-sized Gaussian PLY by deterministic spatial sampling."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "model (1).ply"
TARGET = ROOT / "frontend" / "public" / "assets" / "emotion-field.ply"
STRIDE = 4


def main() -> None:
    with SOURCE.open("rb") as source:
        header_lines: list[bytes] = []
        while True:
            line = source.readline()
            if not line:
                raise RuntimeError("PLY header is incomplete")
            header_lines.append(line)
            if line.strip() == b"end_header":
                break
        header = b"".join(header_lines).decode("ascii")
        count_match = re.search(r"element vertex (\d+)", header)
        if not count_match:
            raise RuntimeError("PLY has no vertex element")
        vertex_count = int(count_match.group(1))
        vertex_section = header.split("element vertex", 1)[1].split("element ", 1)[0]
        properties = re.findall(r"^property float ", vertex_section, flags=re.MULTILINE)
        if len(properties) != 14:
            raise RuntimeError(f"Expected 14 float properties, got {len(properties)}")
        row_size = 14 * 4
        output_count = (vertex_count + STRIDE - 1) // STRIDE
        compact_header = "\n".join([
            "ply",
            "format binary_little_endian 1.0",
            f"element vertex {output_count}",
            "property float x",
            "property float y",
            "property float z",
            "property float f_dc_0",
            "property float f_dc_1",
            "property float f_dc_2",
            "property float opacity",
            "property float scale_0",
            "property float scale_1",
            "property float scale_2",
            "property float rot_0",
            "property float rot_1",
            "property float rot_2",
            "property float rot_3",
            "end_header",
            "",
        ]).encode("ascii")
        TARGET.parent.mkdir(parents=True, exist_ok=True)
        with TARGET.open("wb") as target:
            target.write(compact_header)
            for index in range(vertex_count):
                row = source.read(row_size)
                if len(row) != row_size:
                    raise RuntimeError(f"Unexpected EOF at vertex {index}")
                if index % STRIDE == 0:
                    target.write(row)
    print(f"Wrote {TARGET} ({TARGET.stat().st_size / 1024 / 1024:.1f} MiB)")


if __name__ == "__main__":
    main()
