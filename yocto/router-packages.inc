# Include from an existing OpenSTLinux image recipe or local.conf.
# This is NOT a complete BSP, layer or tested image build.
# Check recipe/package availability against the selected ST release first.
IMAGE_INSTALL:append = " iproute2 nftables dnsmasq modemmanager networkmanager networkmanager-nmcli libqmi libmbim usbutils ethtool "
# Ensure NetworkManager's modemmanager PACKAGECONFIG is enabled in your branch.
# Select exactly one manager per interface; inspect ST's existing network config.
# Retain the BSP's existing systemd, D-Bus and SSH selections.
# Driver/module selection depends on the modem: USB_NET_QMI_WWAN,
# USB_NET_CDC_MBIM, USB_WDM, USB_SERIAL_OPTION as applicable.
# NAT/firewall: NF_TABLES, NF_CONNTRACK, NF_NAT, NFT_NAT, NFT_MASQ,
# NF_TABLES_INET and NFT_CT plus the platform's USB/Ethernet support.
