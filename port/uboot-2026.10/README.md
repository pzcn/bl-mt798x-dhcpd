# WMA301 V2 · U-Boot 2026.10

**CI builds the WMA301 BL33 Web update package, retaining OEM BL2/BL31.**

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
  new `boot_production → boot_recovery → httpd` sequence.
  Upstream already checks the buttons before the boot countdown;
  `check_buttons` is no longer set or executed. A saved legacy
  `bootcmd` invoking it is still migrated in RAM. Missing UBI boot
  scripts are also populated. No `saveenv`.
- **MAC:** the original 6-byte MAC is read from `factory_info+0x1c`
  via the MTD layer, validated and copied to `ethaddr` in RAM.
  `mac_from_mtd=0` can opt out, as on V4. Random Ethernet MAC
  generation is disabled. If the factory MAC is invalid, no bogus MAC
  is installed.
- **Headless Web recovery (Reset or Mesh):** **press and hold Reset
  or Mesh before power-on**, then keep holding through startup.
  **上电后持续按住约 6 秒：红灯常亮后不要松手，直到绿灯开始闪烁再松手。**
  This is an LED-based guide, not an exact elapsed-time guarantee:
  BootROM/BL2, DDR training and physical board startup can vary.
  The default `failsafe_led_idle=red:status on` marks the button-check
  stage and `failsafe_led_ready=green:status blink 1000` marks
  Web recovery. Upstream `common/main.c` executes `btnchk` **before**
  `bootdelay_process()`; `bootcmd` does not run it a second time.
  `btnchk_key=reset,mesh` is supplied by both the default env and
  the board's RAM-only legacy migration, so a stored 2025 environment
  cannot remove this key selection. The recovery UI is at
  `http://192.168.1.1/` and needs no UART. Actual LED behavior and
  button timing still need hardware verification on WMA301 V2.0.
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
`reserved` (0x3c0000, 256 KiB), `factory_info`, `art`,
`config`. The `reserved` partition's purpose is not yet confirmed,
so backing it up may help future factory restoration. The handler streams
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

## Firmware and BL33 Web updates

The dedicated WMABL33 updater is available directly in U-Boot Web recovery.
No TTL authorization or environment-variable switch is required. Uploaded
packages are validated, written to the repacked FIP and read back.

Generic sysupgrade.itb Web flashing is not implemented in this port.
For ImmortalWrt, boot initramfs and use Linux sysupgrade, preserving the
UBI ubootenv and ubootenv2 volumes. The environment editor, Web console,
generic BL2/FIP and UBI management pages remain disabled.

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

BL33 Web updates use WMA301_BL33_UPDATE.bin without a TTL unlock or
write-enable variable. The three-block FIP requirement, integrity checks
and readback verification remain in place.

WMA301_BL33_UPDATE.bin is a BL33 update package, not a full FIP image.

## Build

CI fetches pinned upstream 2026.10, applies `apply.py`, validates the OEM
partition layout and recovery keys, compiles BL33, checks the Web UI and
package format, then uploads the BL33 update artifact.

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

