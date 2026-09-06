-keepclasseswithmembernames class * {
    native <methods>;
}

-keep class com.unsafie.vpn.MyVpnService { *; }
-keep class com.unsafie.vpn.MainActivity { *; }
-keep class com.unsafie.vpn.BootReceiver { *; }
-keep class com.unsafie.vpn.VpnTileService { *; }
-keep class com.unsafie.vpn.UpdateInstallReceiver { *; }
-keep class com.unsafie.vpn.UpdateJobService { *; }
