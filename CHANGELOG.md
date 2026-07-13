# Changelog

## 0.2.1

- Fixed GitHub Actions failure: `Invalid uImage magic at 0x310000`.
- Dynamically detects the ramdisk uImage by header type.
- Preserves uImage metadata and rebuilds header/data CRCs in Python.
- Preserves trailing firmware bytes instead of assuming a fixed image ending.
- Uses deterministic CPIO file ordering.
