# Prepared eMMC installation

Status: user approved and programming completed successfully on 2026-09-23.
CubeProgrammer exited 0 with "Flashing service completed successfully".
The commands below are retained as an execution record, not a request to reflash.
Next step is eMMC boot and Linux console validation.

Target: STM32MP257F-DK, DFU serial `001A00254C42501400313951`, device ID 0x0505.
Image: OpenSTLinux v26.06.10, standard Cortex-A35 OP-TEE Weston starter image.
Purpose: establish Linux for the router project; router services are installed later.

The archive was extracted successfully and all binary paths in the board-specific
eMMC layout were checked. The image hash is recorded in session-status.md; vendor
authenticity has not been independently verified against a published digest.

This operation replaces the eMMC boot firmware, partition layout and Linux
filesystems, and erases the layout's FIP-B/environment entries. Existing contents
were unknown and were not backed up. The user confirmed the write before execution.
Leave power and both USB cables stable during any future programming operation.

Executed PowerShell commands:

```powershell
Set-Location 'C:\Projects\STM32MP257F-DK\local\stm32mp2-openstlinux-6.6-yocto-scarthgap-mpu-v26.06.10\images\stm32mp2'
& 'C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe' -l usb
# Verify USB1 is still the serial above before running the write:
& 'C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer\bin\STM32_Programmer_CLI.exe' -c port=usb1 -w 'flashlayout_st-image-weston/optee/FlashLayout_emmc_stm32mp257f-dk-optee.tsv'
```

After programming succeeds, power down and select Cortex-A35 eMMC boot:
BOOT0=0, BOOT1=1, BOOT2=0, BOOT3=0. Capture the serial console on the next boot
and confirm the OS and network interfaces before installing router configuration.
