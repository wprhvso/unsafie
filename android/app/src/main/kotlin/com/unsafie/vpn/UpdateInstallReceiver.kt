package com.unsafie.vpn

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.os.Build
import android.util.Log

class UpdateInstallReceiver : BroadcastReceiver() {
    companion object {
        private const val TAG = "Unsafie"
        const val ACTION_STATUS = "com.unsafie.vpn.INSTALL_STATUS"
        const val EXTRA_VERSION = "com.unsafie.vpn.VERSION"
    }

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != ACTION_STATUS) {
            return
        }
        val version = intent.getStringExtra(EXTRA_VERSION).orEmpty()
        when (val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, Int.MIN_VALUE)) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                val confirm = confirmation(intent)
                if (confirm == null) {
                    Log.w(TAG, "Update: the installer sent no confirmation intent")
                    forgetStaged(context)
                } else {
                    notifyUpdateReady(context, version, confirm)
                }
            }

            PackageInstaller.STATUS_SUCCESS -> {
                Log.i(TAG, "Update: $version installed")
                cancelUpdateNotification(context)
                forgetStaged(context)
            }

            else -> {
                val message = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE)
                Log.w(TAG, "Update: $version was not installed, status $status ($message)")
                cancelUpdateNotification(context)
                forgetStaged(context)
            }
        }
    }

    private fun confirmation(intent: Intent): Intent? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            intent.getParcelableExtra(Intent.EXTRA_INTENT, Intent::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent.getParcelableExtra(Intent.EXTRA_INTENT)
        }
}
