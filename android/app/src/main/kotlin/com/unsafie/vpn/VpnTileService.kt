package com.unsafie.vpn

import android.app.PendingIntent
import android.content.Intent
import android.net.VpnService
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.onEach

class VpnTileService : TileService() {
    companion object {
        private const val TAG = "Unsafie"
    }

    private var scope: CoroutineScope? = null

    override fun onStartListening() {
        super.onStartListening()
        scope?.cancel()
        val s = CoroutineScope(Dispatchers.Main.immediate + SupervisorJob())
        scope = s
        MyVpnService.running
            .onEach { render(it) }
            .launchIn(s)
    }

    override fun onStopListening() {
        scope?.cancel()
        scope = null
        super.onStopListening()
    }

    override fun onClick() {
        super.onClick()
        if (MyVpnService.running.value) {
            sendCommand(MyVpnService.ACTION_STOP)
            return
        }
        if (isLocked) {
            unlockAndRun { start() }
            return
        }
        start()
    }

    private fun start() {
        if (VpnService.prepare(this) != null) {
            Log.i(TAG, "Tile: VPN consent not granted, opening app")
            launchApp()
            return
        }
        if (!sendCommand(null)) {
            launchApp()
        }
    }

    private fun sendCommand(action: String?): Boolean {
        val intent = Intent(this, MyVpnService::class.java).also { it.action = action }
        return try {
            startForegroundService(intent)
            true
        } catch (e: Exception) {
            Log.e(TAG, "Tile: failed to start the tunnel", e)
            false
        }
    }

    private fun launchApp() {
        val intent =
            Intent(this, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startActivityAndCollapse(
                PendingIntent.getActivity(
                    this,
                    0,
                    intent,
                    PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
                ),
            )
        } else {
            @Suppress("DEPRECATION")
            startActivityAndCollapse(intent)
        }
    }

    private fun render(running: Boolean) {
        val tile = qsTile ?: return
        tile.state = if (running) Tile.STATE_ACTIVE else Tile.STATE_INACTIVE
        tile.updateTile()
    }
}
