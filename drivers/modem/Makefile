# Build unchanged ST sources as external modules against matching devsrc/symvers.
obj-m += cdc-wdm.o cdc_mbim.o qmi_wwan.o
# The shipped kernel omitted these optional modules. Expose their declarations
# in this external build without changing the running kernel configuration.
ccflags-y += -DCONFIG_USB_WDM_MODULE=1 -DCONFIG_USB_NET_CDC_MBIM_MODULE=1 -DCONFIG_USB_NET_QMI_WWAN_MODULE=1
