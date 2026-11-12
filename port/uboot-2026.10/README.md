# WMA301 V2 U-Boot 2026.10 experimental port

**Unverified source migration. Not ready to flash.**

This overlay targets [Yuzhii0718/uboot-airoha-mediatek](https://github.com/Yuzhii0718/uboot-airoha-mediatek)
at commit `628fe8da3a8084f1f43839abb1a5d0470521a2c7` (U-Boot 2026.10-Airoha/Mediatek).
The old 2025.07 code remains untouched on the original `wma301` branch.

## Critical layout correction (2026-11-12)

**Do not use the current temporary OpenWrt SSH shell to flash this package.**
The existing Linux/community device tree and the 2026.10 experimental
U-Boot DTS have a provisional `fip` partition at `0x200000..0x400000`.
The original WMA301 V2 NAND contains the **actual OEM FIP at offset
`0x20000`** inside the stock `factory_boot` area
(`0x0..0x3c0000`). These are different physical regions.

The first port of `wma301_oem_bl33.c` incorrectly required the provisional
`0x200000` address. **This check has been corrected**: the C writer now
requires `fip` at `0x20000`, length `0x3a0000`, 128 KiB erase blocks,
and a 128 MiB parent NAND. With the current provisional device tree this
**must fail closed** rather than write the wrong data. Passing the package
validator does not authorize a raw `mtd write` to `/dev/mtd2`.

To enable a real OEM-only BL33 update, first create and test an OEM-accurate
U-Boot/Linux flash partition map, inspect the physical FIP TOC and backup
its three erase blocks, then test recovery and the dedicated writer.
The stock-toolbox path for an intact OEM firmware uses a different target:
`/dev/mtd0 factory_boot`, size `0x3c0000`, with FIP eraseblocks at
`0x20000`, `0x40000`, `0x60000`. It cannot be used unchanged with the
read-only temporary Linux layout, whose `mtd0` is a 1 MiB `bl2` alias.

## What was ported

- WMA301 V2 board DTS: GPIO0 Mesh, GPIO1 Reset, GPIO14/15 status LEDs,
  2500base-x switch connection, SPI-NAND and OEM observed MTD layout.
- A 2026.10 Kconfig based on the upstream MT7981 360T7 configuration.
- Boot environment: check buttons, load FIT from UBI, fallback to
  recovery FIT, TFTP RAM boot and HTTP failsafe.
- Web recovery supports RAM-boot initramfs, plus **WMABL33 v1 OEM-only BL33
  update** behind a TTL one-shot authorization. The upstream generic FIP,
  BL2, firmware, flash and UBI writers remain inaccessible to Web uploads.
  Telnet, environment editor and Web console are disabled.
- Independent GitHub Actions compilation, WMABL33 v1 package encoding,
  strict decode/round-trip validation, size/link-address checks, ELF header
  inspection and build audit. No FIP, no Release, no automatic flashing.

## Unified Toolbox / V4 Web format (PR #4)

The output is named `WMA301_BL33_UPDATE.bin`: exactly 128 bytes of
`WMABL33\\0` v1 header followed by an XZ/CRC32-compressed BL33. The header
contains the `tplink,wma301-v2` board ID, both sizes, SHA-256 hashes for
compressed and raw BL33, `0x41e00000` load address and zero reserved field.
The encoder and validator live in `package_bl33.py`. The format is identical
in structure to the Toolbox parser merged in
[pzcn/wma301-openwrt PR #4](https://github.com/pzcn/wma301-openwrt/pull/4).

**This is an experimental package despite using the production file format.**
It must not be used in the Toolbox to flash a device, or via V4 Web recovery,
until OEM BL31 compatibility, network and button recovery are verified on
actual WMA301 V2 hardware. A passing package checksum does not make the
unvalidated BL33 flash-safe.

## V4 Toolbox-style Web UI (ported for 2026.10)

The UI sources are copied from the proven V4 design on
`feat/wma301-v4-clean` into `fsdata-wma301/`, and `apply.py` installs
them into the new 2026.10 failsafe resource tree. The 2026.10 Kconfig,
page routing and favicon handler have been adapted to this separate style.

- Original **Toolbox router SVG** for the header and favicon.
- Light mode by default; CSS follows system dark-mode preference.
- V4 navigation, device info and cards. The backend `/sysinfo`
  is enabled, while Web console, environment editor and UBI management
  remain disabled.
- **Initramfs** RAM boot remains usable through `/upload`.
- Firmware flash remains blocked. The **U-Boot 更新** card accepts
  `WMA301_BL33_UPDATE.bin`; the board validation hook checks the package
  and OEM FIP, and the writer is **locked by default** until TTL arms it.
- `/reboot-failsafe` is **blocked on the backend** because the new
  upstream endpoint would call `env_save()`. Normal reboot remains.
- CI checks JavaScript syntax and the gzip-embedded HTML, CSS, JS and
  original SVG after compiling U-Boot.

**Scope:** The V4-specific BL33 writer has now been migrated and builds on
2026.10; the separate generic firmware writer remains disabled. CI does
not confirm that the physical flash can be updated and recovered safely.

### OEM BL33 Web-update interlock

The `fip` HTTP upload field routes to the dedicated
`wma301_oem_bl33_validate()` / `wma301_oem_bl33_write()` implementation,
**not** the upstream full-FIP writer. It only accepts the WMABL33 v1 format,
checks the existing BL31+BL33 FIP TOC, preserves BL31 bytes, verifies the
write by reading back, and attempts restoring the original FIP on failure.

It additionally requires exactly these observed physical conditions:
128 MiB parent MTD, 128 KiB erase blocks, the raw `fip` partition at
0x200000 with 2 MiB size, and the expected BL31/BL33 FIP TOC structure.
Mismatch means **refuse to write**; do not bypass the checks.

For **explicit hardware testing only**, with a verified external backup,
known-good recovery procedure and stable power, a console operator may
temporarily arm one attempt:

```text
MT7981> setenv wma301_bl33_update_enable 1
MT7981> httpd
```

Do **not** run `saveenv`. The variable is in RAM and is cleared before
the actual write. When absent, /upload may validate a package but /result
cannot perform a persistent write. The Web UI displays the same warning.
This is not proof against an interrupted FIP erase or an unbootable new
BL33; restoring the old image after power loss is not guaranteed.

## Important caveats

The observed OEM partition map is BL2 1 MiB, u-boot-env 1 MiB,
FIP 2 MiB, factory 512 KiB, eeprom 512 KiB, stock-config 2 MiB and
remaining UBI. **The new upstream normally expects OpenWrt UBI FIP
layouts.** The WMA301-specific writer bypasses that path and rebuilds
the BL31+BL33 FIP only within the exact OEM `fip` partition. OEM BL2 and
BL31 are not rebuilt or intentionally modified.

`read-only` DTS properties and Web write guards do not prevent writes
from a UART command line or external flashing utilities.

A successful build does not establish hardware compatibility. The
previous WMA301 bootloader experiments exposed serious switch/network
and Reset recovery issues. UART, LAN, ARP, HTTP, watchdog, boot mode,
OEM A/B flag, MAC source and FIT boot all require hardware tests.
Do not write the output `u-boot.bin` directly to NAND or substitute it
for a complete FIP.

## Reproduce

```sh
git clone -b feat/wma301-uboot-2026.10 https://github.com/pzcn/bl-mt798x-dhcpd.git wma301
git clone https://github.com/Yuzhii0718/uboot-airoha-mediatek.git upstream
git -C upstream checkout 628fe8da3a8084f1f43839abb1a5d0470521a2c7
python3 wma301/port/uboot-2026.10/apply.py upstream
npm ci --prefix upstream/failsafe/embedded
make -C upstream mt7981_tplink_wma301v2_experimental_defconfig
make -C upstream olddefconfig
python3 wma301/port/uboot-2026.10/apply.py upstream --verify
make -C upstream -j"$(nproc)" CROSS_COMPILE=aarch64-linux-gnu- all
```

The upstream revision remains pinned to reproduce the passing CI build.
WMABL33 format, C writer compilation and embedded V4 UI have passed CI;
**the OEM FIP Web writing path has not yet been proven on real hardware and is intentionally blocked by the current incompatible partition map**.
Future source updates should stay behind this same verification pipeline.
