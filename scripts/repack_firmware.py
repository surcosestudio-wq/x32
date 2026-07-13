#!/usr/bin/env python3
"""Replace OMC and SHARC loader files inside an unencrypted OpenX32 .run image."""
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

RAMDISK_OFFSET = 0x310000
UIMAGE_HEADER_SIZE = 64
UIMAGE_MAGIC = 0x27051956


def run(cmd, cwd=None, stdin=None):
    print('+', ' '.join(map(str, cmd)))
    subprocess.run(cmd, cwd=cwd, stdin=stdin, check=True)


def parse_uimage(blob: bytes):
    if len(blob) < UIMAGE_HEADER_SIZE:
        raise RuntimeError('Ramdisk image is too small')
    magic = struct.unpack('>I', blob[0:4])[0]
    if magic != UIMAGE_MAGIC:
        raise RuntimeError(f'Invalid uImage magic at 0x{RAMDISK_OFFSET:X}: 0x{magic:08X}')
    payload_size = struct.unpack('>I', blob[12:16])[0]
    end = UIMAGE_HEADER_SIZE + payload_size
    if end > len(blob):
        raise RuntimeError('uImage payload length exceeds firmware image')
    return blob[UIMAGE_HEADER_SIZE:end]


def decompress_payload(payload: bytes):
    if payload.startswith(b'\x1f\x8b'):
        return gzip.decompress(payload), 'gzip'
    # Legacy .lzma stream commonly begins with 0x5d and dictionary bytes.
    try:
        return lzma.decompress(payload, format=lzma.FORMAT_ALONE), 'lzma'
    except lzma.LZMAError as exc:
        raise RuntimeError('Unsupported ramdisk compression (not gzip or LZMA-alone)') from exc


def compress_payload(data: bytes, kind: str) -> tuple[bytes, str]:
    if kind == 'gzip':
        return gzip.compress(data, compresslevel=9, mtime=0), 'initramfs.cpio.gz'
    if kind == 'lzma':
        filters = [{"id": lzma.FILTER_LZMA1, "dict_size": 1024 * 1024}]
        return lzma.compress(data, format=lzma.FORMAT_ALONE, filters=filters), 'initramfs.cpio.lzma'
    raise RuntimeError(f'Unknown compression: {kind}')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--base-run', required=True, type=Path)
    ap.add_argument('--omc', required=True, type=Path)
    ap.add_argument('--dsp1', required=True, type=Path)
    ap.add_argument('--dsp2', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--scripts-dir', required=True, type=Path)
    args = ap.parse_args()

    for path in (args.base_run, args.omc, args.dsp1, args.dsp2):
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f'Missing or empty input: {path}')

    with tempfile.TemporaryDirectory(prefix='surcos-x32-') as td:
        td = Path(td)
        dcp_dir = td / 'dcp'
        dcp_dir.mkdir()
        shutil.copy2(args.base_run, dcp_dir / 'base.run')
        run(['perl', str(args.scripts_dir / 'dcp_decompiler.pl'), 'base.run'], cwd=dcp_dir)

        app = dcp_dir / 'binary' / 'dcpapp.bin'
        if not app.is_file():
            raise RuntimeError('DCP image did not contain binary/dcpapp.bin')
        firmware = app.read_bytes()
        if len(firmware) <= RAMDISK_OFFSET + UIMAGE_HEADER_SIZE:
            raise RuntimeError('Base firmware is smaller than expected')

        payload = parse_uimage(firmware[RAMDISK_OFFSET:])
        cpio_data, compression = decompress_payload(payload)
        print(f'Ramdisk compression: {compression}; uncompressed bytes: {len(cpio_data)}')

        rootfs = td / 'rootfs'
        rootfs.mkdir()
        cpio_path = td / 'initramfs.cpio'
        cpio_path.write_bytes(cpio_data)
        with cpio_path.open('rb') as fh:
            run(['cpio', '-idmu', '--no-absolute-filenames'], cwd=rootfs, stdin=fh)

        target = rootfs / 'openx32'
        expected = [target / 'omc', target / 'dsp1.ldr', target / 'dsp2.ldr']
        for p in expected:
            if not p.exists():
                raise RuntimeError(f'Base release does not contain expected file: {p.relative_to(rootfs)}')

        shutil.copy2(args.omc, target / 'omc')
        shutil.copy2(args.dsp1, target / 'dsp1.ldr')
        shutil.copy2(args.dsp2, target / 'dsp2.ldr')
        os.chmod(target / 'omc', 0o755)

        new_cpio = td / 'new-initramfs.cpio'
        # Stable ordering makes the artifact more reproducible.
        file_list = subprocess.check_output(['find', '.', '-print0'], cwd=rootfs)
        with new_cpio.open('wb') as out:
            proc = subprocess.run(
                ['cpio', '--null', '-ov', '--format=newc'],
                cwd=rootfs,
                input=file_list,
                stdout=out,
                check=True,
            )

        compressed, compressed_name = compress_payload(new_cpio.read_bytes(), compression)
        compressed_path = td / compressed_name
        compressed_path.write_bytes(compressed)
        new_uimage = td / 'uramdisk.bin'
        run([
            'mkimage', '-A', 'ARM', '-O', 'linux', '-T', 'ramdisk', '-C', 'none',
            '-a', '0', '-e', '0', '-n', 'Ramdisk Image (Surcos X32 EQ2404)',
            '-d', str(compressed_path), str(new_uimage)
        ])

        # Ramdisk is the final component in openx32.bin. Preserve everything before it.
        rebuilt_app = firmware[:RAMDISK_OFFSET] + new_uimage.read_bytes() + (b'\0' * 100)
        new_app = td / 'openx32-surcos.bin'
        new_app.write_bytes(rebuilt_app)

        args.output.parent.mkdir(parents=True, exist_ok=True)
        run([
            'perl', str(args.scripts_dir / 'dcp_compiler.pl'),
            f'{new_app}:binary/dcpapp.bin', str(args.output)
        ])

        if not args.output.is_file() or args.output.stat().st_size == 0:
            raise RuntimeError('Output .run was not generated')
        print(f'Created: {args.output} ({args.output.stat().st_size} bytes)')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise
