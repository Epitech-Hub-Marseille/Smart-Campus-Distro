#!/usr/bin/env python3
"""Write a small solid-colour PNG: solid-png.py <output.png> <#rrggbb>.

Used for the Plymouth progress bar images, so the image build needs no
imaging library for flat colours.
"""
import struct
import sys
import zlib

SIZE = 8


def chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))


def solid_png(red: int, green: int, blue: int) -> bytes:
    row = b"\x00" + bytes([red, green, blue]) * SIZE  # filter byte 0 + pixels
    header = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 2, 0, 0, 0)  # 8-bit RGB
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(row * SIZE)) + chunk(b"IEND", b""))


def main() -> int:
    if len(sys.argv) != 3 or len(sys.argv[2]) != 7 or not sys.argv[2].startswith("#"):
        print("usage: solid-png.py <output.png> <#rrggbb>", file=sys.stderr)
        return 2
    red, green, blue = (int(sys.argv[2][i:i + 2], 16) for i in (1, 3, 5))
    with open(sys.argv[1], "wb") as out:
        out.write(solid_png(red, green, blue))
    return 0


if __name__ == "__main__":
    sys.exit(main())
