# WMA301 V2 · U-Boot 2026.10 experimental port

**CI builds an experimental BL33, not a complete FIP. Hardware flash and recovery remain unverified.**

This overlay pins [Yuzhii0718/uboot-airoha-mediatek](https://github.com/Yuzhii0718/uboot-airoha-mediatek) at `628fe8da3a8084f1f43839abb1a5d0470521a2c7` (2026.10). The stable `wma301` / 2025.07 branch remains unchanged.

## OEM flash layout, identical to 2025

128 MiB SPI NAND, erase size 128 KiB. The board DTS, Kconfig
`mtdparts` defaults and runtime MTD initialization must agree:

| Partition | Start | Size | Policy |
|---|---:|---:|---|
| `bl2` | `0x000000` | 128 KiB | Read-only |
| `fip` | `0x020000` | 3,712 KiB | Read-only to generic MTD |
| `reserved` | `0x3c0000` | 256 KiB | Read-only |
| `factory_info` | `0x400000` | 512 KiB | Read-only, MAC at +`0x1c` |
| `art` | `0x480000` | 512 KiB | Read-only calibration |
| `config` | `0x500000` | 2 MiB | Read-only |
| `ubi` | `0x700000` | remainder, 121 MiB | UBI data |

The exact inherited 2025 layout string is:

```text
spi-nand0:128k(bl2)ro,3712k(fip)ro,256k(reserved)ro,512k(factory_info)ro,512k(art)ro,2048k(config)ro,-(ubi)
```

The board compatibility module resets `mtdids` / `mtdparts` to
this layout **in RAM only** after loading any saved UBI environment.
No partition table is flashed as part of BL33 migration.

## 2025 environment, MAC, Mesh and LEDs

- **2025 bootcmd migration:** U-Boot 2025 may have persisted
  `bootcmd=mtkboardboot` in `ubootenv` / `ubootenv2`. That command does
  not exist in 2026.10. At `board_late_init`, an empty/missing `bootcmd`,
  or one containing `mtkboardboot`, is replaced **in RAM** with the
  new `check_buttons → boot_production → boot_recovery → httpd`
  sequence. Missing UBI boot scripts are also populated. No `saveenv`.
- **MAC:** the original 6-byte MAC is read from `factory_info+0x1c`
  via the MTD layer, validated and copied to `ethaddr` in RAM.
  `mac_from_mtd=0` can opt out, as on V4. Random Ethernet MAC
  generation is disabled. If the factory MAC is invalid, no bogus MAC
  is installed.
- **Headless Web recovery (Reset or Mesh):** hold either physical
  button **starting before power-on** and keep holding until the recovery
  LED/Web server is active (allow roughly **6–9 seconds** from power-on,
  depending on BL2/DDR init and network bring-up; do not release at only
  4 seconds). Upstream 2026.10 `common/main.c` already runs `btnchk`
  **before** `bootdelay_process()`; adding `preboot=run check_buttons`
  would duplicate detection. We removed the second button check from
  `bootcmd` instead. `btnchk_key=reset,mesh`
  and `check_buttons=btnchk` are set both in the default env and
  in `board_late_init` after any stored 2025 environment is imported.
  Upstream 2026.10 excludes Reset only from its *default* key list:
  an explicitly configured Reset label is supported. A successful
  hold starts `httpd` directly at `http://192.168.1.1/`,
  **without UART interaction**. This must still be proven on actual
  WMA301 V2.0 hardware.
- **Manual TTL bootmenu:** at the serial `MT7981>` prompt, run
  `bootmenu` for installed FIT, recovery FIT, TFTP **RAM boot**,
  Web failsafe and reboot. Neither physical button starts a menu
  automatically. No raw NAND-writing menu actions are present.
- **Reset early handling:** the upstream board can select defaults
  instead of persisted variables when Reset is detected. Its serial
  message about "resetting environment" means **RAM-only defaults for
  this boot**, not erasing the stored `ubootenv` volumes. The default
  `btnchk_key` includes both physical buttons. Holding Reset is not
  a remedy for corrupt BL2/FIP.
- **LED polarity:** on measured V2.0 hardware, GPIO14 red and GPIO15
  green are both **active HIGH**. GPIO0 Mesh and GPIO1 Reset remain
  active LOW.

## Read-only Web backups

The standalone `/backup/info` (GET) and `/backup/main` (POST)
endpoints preserve the V4/Toolbox protocol. Only these named, OEM-map
matched partitions may be downloaded: `bl2`, `fip`,
`factory_info`, `art`, `config`. The handler streams
`mtd_read` responses in 16 KiB chunks with the correct
`Content-Length`, without loading the entire FIP in U-Boot RAM.
It exposes no full-chip or arbitrary range backups and performs no
writes or erases. The generic `WEBUI_FAILSAFE_FLASH` module stays off.
`/sysinfo` also reports `mac` (the validated runtime `ethaddr`),
so the V4 interface can display it while `/env/list` is disabled.

A backup can include private device identifiers and sensitive settings:
disconnect WAN and keep backup files private. HTTP recovery has no
account login. A NAND with ECC/read errors may cause a backup to abort;
the client must verify `Content-Length` and repeat critical reads.

## Firmware Web upgrade is intentionally disabled

The V4 UI and upstream Web failsafe framework are present. For now,
`initramfs` RAM boot works, and the dedicated `WMABL33` BL33 update
endpoint exists behind the TTL write interlock. **The 2025 Web
`sysupgrade.itb` / generic firmware flash flow is deliberately
disabled in the 2026.10 experiment.** This is an explicit temporary
regression, not a successful full port.

Until the UBI `fit` writer, image checks, readback and persistent-volume
preservation have been verified, first boot a suitable ImmortalWrt
initramfs and upgrade using the tested Linux sysupgrade mechanism.
Preserve the UBI `ubootenv` and `ubootenv2` volumes (approximately
124 KiB each); do not recreate the whole NAND image blindly.
Environment editor, Web console, generic FIP/BL2, raw flash and UBI
management pages are also disabled. The upstream `reboot-failsafe`
endpoint that saves environment changes is blocked.

## WMABL33 v1, three-block limit and eligibility

CI packages `WMA301_BL33_UPDATE.bin` with a 128-byte
`WMABL33\0` v1 header and an XZ/CRC32-compressed BL33. It checks the
board ID `tplink,wma301-v2`, both SHA-256 digests, the uncompressed
load address `0x41e00000`, and payload sizes. The binary contract
matches [Toolbox PR #4](https://github.com/pzcn/wma301-openwrt/pull/4).

The OEM FIP begins at physical `0x20000`; the compressed BL33
begins at approximately `0x23848`. The rewritten FIP must end no
later than `0x80000`. The dedicated writer checks the exact 128 MiB
NAND geometry, FIP ToC, original BL31 bytes and the three 128-KiB
eraseblocks, and performs bytewise write/readback validation.

**Only already-customized, three-block FIPs qualify.** The original
stock FIP normally extends well past `0x80000`; the dedicated
update writer deliberately rejects it, without erasing NAND.
A factory-original WMA301 requires a verified first-install
Toolbox method or serial/BootROM procedure; merely supplying a
WMABL33 package to an original FIP is not supported.

BL33 Web writing is **locked by default**. A test operator with a
full per-device FIP backup and a known-good rescue path may set the
`wma301_bl33_update_enable=1` variable **only in RAM via TTL**.
It is cleared during every boot and before a write. Never use
`saveenv` for this authorization.

`WMA301_BL33_UPDATE.bin` is **not** a complete FIP or NAND image.
Never pass it directly to `mtd write` / `nand write`. A successful
CI build does not demonstrate flash-write, power-loss or rollback safety.

## Build

CI fetches pinned upstream 2026.10, applies `apply.py`, audits
the 2025 partition layout, both headless Web-recovery keys and legacy
migration, compiles BL33, checks
V4 UI embedding and package contents, and uploads an explicitly
**experimental / not-for-flashing** artifact. It does not publish
a release or modify any router.

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

Still required on actual hardware: legacy saved-env boot, factory MAC,
LED polarity, Reset and Mesh recovery without TTL, download streaming
and backup hashes, manual serial menu, FIT volume naming and safe
FIP/UBI recovery.
