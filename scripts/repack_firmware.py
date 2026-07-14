#!/usr/bin/env python3
"""Replace only OMC and DSP1 inside a compatible OpenX32 .run image."""
from __future__ import annotations

import argparse
import gzip
import lzma
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

UIMAGE_HEADER_SIZE = 64
UIMAGE_MAGIC = 0x27051956
UIMAGE_MAGIC_BYTES = struct.pack(">I", UIMAGE_MAGIC)
UIMAGE_TYPE_RAMDISK = 3


def run(cmd, cwd=None, stdin=None, input_data=None, stdout=None):
    print("+", " ".join(map(str, cmd)))
    subprocess.run(
        cmd,
        cwd=cwd,
        stdin=stdin,
        input=input_data,
        stdout=stdout,
        check=True,
    )


def parse_uimage_at(blob: bytes, offset: int) -> dict[str, object]:
    end_header = offset + UIMAGE_HEADER_SIZE
    if offset < 0 or end_header > len(blob):
        raise RuntimeError(f"uImage header outside firmware at 0x{offset:X}")

    header = blob[offset:end_header]
    (
        magic,
        header_crc,
        timestamp,
        payload_size,
        load_address,
        entry_point,
        data_crc,
        os_id,
        arch_id,
        image_type,
        compression_id,
        raw_name,
    ) = struct.unpack(">7I4B32s", header)

    if magic != UIMAGE_MAGIC:
        raise RuntimeError(f"Invalid uImage magic at 0x{offset:X}: 0x{magic:08X}")

    payload_end = end_header + payload_size
    if payload_end > len(blob):
        raise RuntimeError(
            f"uImage payload at 0x{offset:X} exceeds firmware size "
            f"({payload_size} bytes)"
        )

    header_for_crc = bytearray(header)
    header_for_crc[4:8] = b"\0\0\0\0"
    calculated_header_crc = zlib.crc32(header_for_crc) & 0xFFFFFFFF
    payload = blob[end_header:payload_end]
    calculated_data_crc = zlib.crc32(payload) & 0xFFFFFFFF

    name = raw_name.split(b"\0", 1)[0].decode("ascii", errors="replace")

    return {
        "offset": offset,
        "end": payload_end,
        "header_crc": header_crc,
        "header_crc_valid": header_crc == calculated_header_crc,
        "timestamp": timestamp,
        "payload_size": payload_size,
        "load_address": load_address,
        "entry_point": entry_point,
        "data_crc": data_crc,
        "data_crc_valid": data_crc == calculated_data_crc,
        "os_id": os_id,
        "arch_id": arch_id,
        "image_type": image_type,
        "compression_id": compression_id,
        "name": name,
        "payload": payload,
    }


def find_ramdisk_uimage(blob: bytes) -> dict[str, object]:
    candidates: list[dict[str, object]] = []
    start = 0

    while True:
        offset = blob.find(UIMAGE_MAGIC_BYTES, start)
        if offset < 0:
            break
        start = offset + 1

        try:
            image = parse_uimage_at(blob, offset)
        except RuntimeError:
            continue

        if image["image_type"] == UIMAGE_TYPE_RAMDISK:
            candidates.append(image)

    if not candidates:
        offsets = []
        start = 0
        while True:
            offset = blob.find(UIMAGE_MAGIC_BYTES, start)
            if offset < 0:
                break
            offsets.append(f"0x{offset:X}")
            start = offset + 1
        found = ", ".join(offsets) if offsets else "none"
        raise RuntimeError(
            "No valid ramdisk uImage was found inside binary/dcpapp.bin. "
            f"uImage magic locations found: {found}"
        )

    # OpenX32 stores the initramfs after the kernel and DTB, so the last
    # ramdisk uImage is the correct one even if a future image adds others.
    image = max(candidates, key=lambda candidate: int(candidate["offset"]))
    print(
        "Found ramdisk uImage at "
        f"0x{int(image['offset']):X}: name={image['name']!r}, "
        f"payload={image['payload_size']} bytes, "
        f"header_crc={'OK' if image['header_crc_valid'] else 'MISMATCH'}, "
        f"data_crc={'OK' if image['data_crc_valid'] else 'MISMATCH'}"
    )
    return image


def decompress_payload(payload: bytes) -> tuple[bytes, str]:
    if payload.startswith(b"\x1f\x8b"):
        return gzip.decompress(payload), "gzip"

    try:
        return lzma.decompress(payload, format=lzma.FORMAT_ALONE), "lzma"
    except lzma.LZMAError as exc:
        raise RuntimeError(
            "Unsupported ramdisk compression (payload is not gzip or LZMA-alone)"
        ) from exc


def compress_payload(data: bytes, kind: str) -> bytes:
    if kind == "gzip":
        return gzip.compress(data, compresslevel=9, mtime=0)
    if kind == "lzma":
        filters = [{"id": lzma.FILTER_LZMA1, "dict_size": 1024 * 1024}]
        return lzma.compress(data, format=lzma.FORMAT_ALONE, filters=filters)
    raise RuntimeError(f"Unknown compression: {kind}")


def build_uimage(payload: bytes, original: dict[str, object], name: str) -> bytes:
    encoded_name = name.encode("ascii", errors="replace")[:32].ljust(32, b"\0")
    data_crc = zlib.crc32(payload) & 0xFFFFFFFF

    header = struct.pack(
        ">7I4B32s",
        UIMAGE_MAGIC,
        0,
        int(original["timestamp"]),
        len(payload),
        int(original["load_address"]),
        int(original["entry_point"]),
        data_crc,
        int(original["os_id"]),
        int(original["arch_id"]),
        int(original["image_type"]),
        int(original["compression_id"]),
        encoded_name,
    )
    header_crc = zlib.crc32(header) & 0xFFFFFFFF
    header = header[:4] + struct.pack(">I", header_crc) + header[8:]
    return header + payload


def sorted_find_list(rootfs: Path) -> bytes:
    raw = subprocess.check_output(["find", ".", "-print0"], cwd=rootfs)
    entries = [entry for entry in raw.split(b"\0") if entry]
    entries.sort()
    return b"\0".join(entries) + b"\0"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-run", required=True, type=Path)
    parser.add_argument("--omc", required=True, type=Path)
    parser.add_argument("--dsp1", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--scripts-dir", required=True, type=Path)
    args = parser.parse_args()

    for path in (args.base_run, args.omc, args.dsp1):
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"Missing or empty input: {path}")

    with tempfile.TemporaryDirectory(prefix="surcos-x32-") as temporary_dir:
        temporary = Path(temporary_dir)
        dcp_dir = temporary / "dcp"
        dcp_dir.mkdir()
        shutil.copy2(args.base_run, dcp_dir / "base.run")
        run(
            ["perl", str(args.scripts_dir / "dcp_decompiler.pl"), "base.run"],
            cwd=dcp_dir,
        )

        app = dcp_dir / "binary" / "dcpapp.bin"
        if not app.is_file():
            raise RuntimeError("DCP image did not contain binary/dcpapp.bin")
        firmware = app.read_bytes()

        ramdisk = find_ramdisk_uimage(firmware)
        cpio_data, compression = decompress_payload(ramdisk["payload"])
        print(
            f"Ramdisk compression: {compression}; "
            f"uncompressed bytes: {len(cpio_data)}"
        )

        rootfs = temporary / "rootfs"
        rootfs.mkdir()
        cpio_path = temporary / "initramfs.cpio"
        cpio_path.write_bytes(cpio_data)
        with cpio_path.open("rb") as input_file:
            run(
                ["cpio", "-idmu", "--no-absolute-filenames"],
                cwd=rootfs,
                stdin=input_file,
            )

        target = rootfs / "openx32"
        expected = [target / "omc", target / "dsp1.ldr", target / "dsp2.ldr"]
        for expected_file in expected:
            if not expected_file.exists():
                raise RuntimeError(
                    "Base release does not contain expected file: "
                    f"{expected_file.relative_to(rootfs)}"
                )

        shutil.copy2(args.omc, target / "omc")
        shutil.copy2(args.dsp1, target / "dsp1.ldr")
        os.chmod(target / "omc", 0o755)

        new_cpio = temporary / "new-initramfs.cpio"
        file_list = sorted_find_list(rootfs)
        with new_cpio.open("wb") as output_file:
            run(
                ["cpio", "--null", "-ov", "--format=newc"],
                cwd=rootfs,
                input_data=file_list,
                stdout=output_file,
            )

        compressed = compress_payload(new_cpio.read_bytes(), compression)
        new_uimage = build_uimage(
            compressed,
            ramdisk,
            "Ramdisk Image (Surcos EQ2404)",
        )

        ramdisk_offset = int(ramdisk["offset"])
        old_ramdisk_end = int(ramdisk["end"])
        rebuilt_firmware = (
            firmware[:ramdisk_offset]
            + new_uimage
            + firmware[old_ramdisk_end:]
        )

        # Validate the uImage we just created before packaging it.
        rebuilt_ramdisk = parse_uimage_at(rebuilt_firmware, ramdisk_offset)
        if not rebuilt_ramdisk["header_crc_valid"]:
            raise RuntimeError("Rebuilt ramdisk uImage header CRC is invalid")
        if not rebuilt_ramdisk["data_crc_valid"]:
            raise RuntimeError("Rebuilt ramdisk uImage data CRC is invalid")

        new_app = temporary / "openx32-surcos.bin"
        new_app.write_bytes(rebuilt_firmware)

        args.output.parent.mkdir(parents=True, exist_ok=True)
        run(
            [
                "perl",
                str(args.scripts_dir / "dcp_compiler.pl"),
                f"{new_app}:binary/dcpapp.bin",
                str(args.output),
            ]
        )

        if not args.output.is_file() or args.output.stat().st_size == 0:
            raise RuntimeError("Output .run was not generated")
        print(f"Created: {args.output} ({args.output.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
