include $(TOPDIR)/rules.mk

PKG_NAME:=stm32-lte-router
PKG_VERSION:=1.0.0
PKG_RELEASE:=28
PKG_BUILD_DIR:=$(BUILD_DIR)/$(PKG_NAME)

include $(INCLUDE_DIR)/package.mk

define Package/stm32-lte-router
  SECTION:=net
  CATEGORY:=Network
  TITLE:=STM32 LTE router settings and provisioning
  DEPENDS:=+python3 +python3-paho-mqtt +blkid +e2fsprogs +tune2fs +uboot-envtools +dnsmasq +firewall4 +nftables-json +rpcd +uci +ubus +modemmanager +kmod-usb-net-cdc-mbim +kmod-usb-net-qmi-wwan +kmod-usb-serial-option +ddns-scripts +ddns-scripts-services +ddns-scripts-noip +curl +ca-bundle +openvpn-openssl +openssl-util
endef

define Package/stm32-lte-router/conffiles
/etc/router-web/
endef

define Build/Prepare
	$(INSTALL_DIR) $(PKG_BUILD_DIR)
	$(CP) ./src/. $(PKG_BUILD_DIR)/
endef

define Build/Compile
endef

define Package/stm32-lte-router/install
	$(INSTALL_DIR) $(1)/usr/lib/router-web $(1)/etc/init.d $(1)/etc/router-web $(1)/lib/upgrade/keep.d $(1)/etc/hotplug.d/openvpn
	$(INSTALL_DATA) $(PKG_BUILD_DIR)/* $(1)/usr/lib/router-web/
	$(INSTALL_BIN) ./router-web.init $(1)/etc/init.d/router-web
	$(INSTALL_BIN) ./router-serial.init $(1)/etc/init.d/router-serial
	$(INSTALL_BIN) ./router-at.init $(1)/etc/init.d/router-at
	$(INSTALL_BIN) ./router-modbus.init $(1)/etc/init.d/router-modbus
	$(INSTALL_BIN) ./router-mqtt.init $(1)/etc/init.d/router-mqtt
	$(INSTALL_BIN) ./router-update-confirm.init $(1)/etc/init.d/router-update-confirm
	$(INSTALL_BIN) ./router-storage.init $(1)/etc/init.d/router-storage
	$(INSTALL_BIN) ./router-traffic.init $(1)/etc/init.d/router-traffic
	$(INSTALL_DIR) $(1)/lib/preinit
	$(INSTALL_DATA) ./router-storage.preinit $(1)/lib/preinit/09_router_storage
	$(INSTALL_BIN) ./router-openvpn.hotplug $(1)/etc/hotplug.d/openvpn/30-router
	$(INSTALL_DATA) ./sysupgrade.keep $(1)/lib/upgrade/keep.d/stm32-lte-router
endef

$(eval $(call BuildPackage,stm32-lte-router))
