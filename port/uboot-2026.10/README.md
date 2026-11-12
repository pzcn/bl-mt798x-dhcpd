# WMA301 V2 U-Boot 2026.10 experimental port

**Unverified source migration. Not ready to flash.**

This overlay targets [Yuzhii0718/uboot-airoha-mediatek](https://github.com/Yuzhii0718/uboot-airoha-mediatek)
at commit `628fe8da3a8084f1f43839abb1a5d0470521a2c7` (U-Boot 2026.10-Airoha/Mediatek).
The old 2025.07 code remains untouched on the original `wma301` branch.

## What was ported

- WMA301 V2 board DTS: GPIO0 Mesh, GPIO1 Reset, GPIO14/15 status LEDs,
  2500base-x switch connection, SPI-NAND and OEM observed MTD layout.
- A 2026.10 Kconfig based on the upstream MT7981 360T7 configuration.
- Boot environment: check buttons, load FIT from UBI, fallback to
  recovery FIT, TFTP RAM boot and HTTP failsafe.
- Web recovery is **RAM-only**. All non-initramfs Web uploads are rejected
  during validation, and all persistent Web writes are rejected at the
  actual `failsafe_write_image()` hook. Flash management, UBI management,
  Telnet, environment editor and Web console are disabled.
- Independent GitHub Actions compilation, size check, ELF header inspection
  and a build audit. No FIP, no Release, no automatic flashing.

## Important caveats

The observed OEM partition map is BL2 1 MiB, u-boot-env 1 MiB,
FIP 2 MiB, factory 512 KiB, eeprom 512 KiB, stock-config 2 MiB and
remaining UBI. **The new upstream normally expects OpenWrt UBI FIP
layouts.** It cannot safely replace the OEM FIP without additional
integration. OEM BL2 and BL31 are not built or changed here.

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

The upstream revision is deliberately pinned until the first successful
CI build and a safe RAM-only board bring-up. Later updates can be tested
independently before changing the pinned revision.
