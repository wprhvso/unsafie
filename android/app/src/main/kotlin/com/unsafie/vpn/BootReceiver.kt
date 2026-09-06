package com.unsafie.vpn

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.util.Log

class BootReceiver : BroadcastReceiver() {
    companion object {
        private const val TAG = "Unsafie"
    }

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED && intent.action != Intent.ACTION_MY_PACKAGE_REPLACED) {
            return
        }

        scheduleUpdates(context)

        if (intent.action == Intent.ACTION_MY_PACKAGE_REPLACED) {
            cancelUpdateNotification(context)
            forgetStaged(context)
            return
        }

        if (!autostartEnabled(context)) {
            Log.i(TAG, "Boot: the tunnel was switched off by the user, skipping autostart")
            return
        }

        if (VpnService.prepare(context) != null) {
            Log.i(TAG, "Boot: VPN consent not granted, skipping autostart")
            return
        }

        Log.i(TAG, "Boot: starting the tunnel")
        try {
            context.startForegroundService(Intent(context, MyVpnService::class.java))
        } catch (e: Exception) {
            Log.e(TAG, "Boot: failed to start the tunnel", e)
        }
    }
}
