package com.unsafie.vpn

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import android.util.Log
import java.io.File
import java.util.concurrent.Executors
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

class MyVpnService : VpnService() {
    companion object {
        private const val TAG = "Unsafie"
        private const val CHANNEL_ID = "vpn_channel"
        private const val NOTIFICATION_ID = 1
        private const val MTU = 1400
        const val ACTION_STOP = "com.unsafie.vpn.STOP"

        private val _running = MutableStateFlow(false)
        val running: StateFlow<Boolean> = _running.asStateFlow()

        init {
            System.loadLibrary("unsafie")
        }
    }

    private external fun setStateDir(dir: String)

    private external fun startGoCore(fd: Int, mtu: Int)

    private external fun stopGoCore()

    @Suppress("UnusedPrivateMember")
    private external fun isGoCoreRunning(): Boolean

    private external fun logCoreStatus()

    private val executor = Executors.newSingleThreadExecutor()

    @Volatile
    private var running = false

    @Volatile
    private var stopping = false

    @Volatile
    private var stopPending = false

    private val lock = Any()

    override fun onCreate() {
        super.onCreate()
        scheduleUpdates(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent == null) {
            Log.i(TAG, "Restarted by system (null intent)")
        }

        startForegroundNotification()

        if (intent?.action == ACTION_STOP) {
            Log.i(TAG, "Stop requested from UI")
            rememberAutostart(this, false)
            stopping = true
            stopPending = true
            submit {
                try {
                    stopEngine()
                    stopForeground(Service.STOP_FOREGROUND_REMOVE)
                    stopSelf(startId)
                } finally {
                    stopPending = false
                }
            }
            return START_NOT_STICKY
        }

        stopping = false
        synchronized(lock) {
            if (running && !stopPending) {
                Log.i(TAG, "Engine already running; ignoring start request")
                return START_STICKY
            }
        }

        submit { setupTunnel() }
        return START_STICKY
    }

    private fun submit(task: () -> Unit) {
        try {
            executor.execute { task() }
        } catch (e: RejectedExecutionException) {
            Log.w(TAG, "The service is shutting down; dropping the request", e)
        }
    }

    private fun startForegroundNotification() {
        val channel =
            NotificationChannel(
                CHANNEL_ID,
                getString(R.string.app_name),
                NotificationManager.IMPORTANCE_LOW,
            )
        getSystemService(NotificationManager::class.java)?.createNotificationChannel(channel)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(
                NOTIFICATION_ID,
                createNotification(),
                ServiceInfo.FOREGROUND_SERVICE_TYPE_SYSTEM_EXEMPTED,
            )
        } else {
            startForeground(NOTIFICATION_ID, createNotification())
        }
    }

    private fun setupTunnel() {
        synchronized(lock) {
            if (running || stopping) return
        }

        val pfd: ParcelFileDescriptor?
        try {
            pfd =
                Builder()
                    .setSession(getString(R.string.app_name))
                    .setMtu(MTU)
                    .addAddress("10.0.0.2", 24)
                    .addAddress("fd00:dead:beef::2", 64)
                    .addRoute("0.0.0.0", 0)
                    .addRoute("::", 0)
                    .addDnsServer("10.0.0.1")
                    .addDisallowedApplication(packageName)
                    .establish()
        } catch (e: Exception) {
            Log.e(TAG, "Failed to build TUN interface", e)
            stopSelf()
            return
        }

        if (pfd == null) {
            Log.e(TAG, "establish() returned null; permission revoked or another VPN is active")
            stopSelf()
            return
        }

        val fd = pfd.detachFd()
        Log.i(TAG, "TUN established, fd=$fd mtu=$MTU")

        try {
            setStateDir(File(filesDir, "sessions").absolutePath)
            startGoCore(fd, MTU)
            synchronized(lock) { running = true }
            _running.value = true
            rememberAutostart(this, true)
            logCoreStatus()
        } catch (e: Throwable) {
            Log.e(TAG, "startGoCore failed", e)
            try {
                ParcelFileDescriptor.adoptFd(fd).close()
            } catch (ignored: Exception) {
            }
            stopSelf()
            return
        }

        if (stopping) {
            Log.i(TAG, "Stop requested while the tunnel was coming up; tearing down")
            stopEngine()
            stopForeground(Service.STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    private fun stopEngine() {
        synchronized(lock) {
            if (!running) return
            running = false
        }
        try {
            stopGoCore()
            Log.i(TAG, "Core stopped")
        } catch (e: Throwable) {
            Log.e(TAG, "stopGoCore failed", e)
        }
        _running.value = false
    }

    override fun onRevoke() {
        Log.i(TAG, "VPN permission revoked")
        rememberAutostart(this, false)
        stopping = true
        submit {
            stopEngine()
            stopForeground(Service.STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
        super.onRevoke()
    }

    override fun onDestroy() {
        Log.i(TAG, "Service destroying")
        stopping = true
        try {
            executor.submit { stopEngine() }.get(3, TimeUnit.SECONDS)
        } catch (e: Exception) {
            Log.w(TAG, "Engine shutdown did not complete in time", e)
        }
        executor.shutdown()
        try {
            executor.awaitTermination(3, TimeUnit.SECONDS)
        } catch (e: InterruptedException) {
            Thread.currentThread().interrupt()
        }
        super.onDestroy()
    }

    private fun createNotification(): Notification {
        val pendingIntent =
            PendingIntent.getActivity(
                this,
                0,
                Intent(this, MainActivity::class.java),
                PendingIntent.FLAG_IMMUTABLE,
            )
        return Notification
            .Builder(this, CHANNEL_ID)
            .setContentTitle(getString(R.string.notification_title))
            .setContentText(getString(R.string.notification_text))
            .setSmallIcon(android.R.drawable.ic_menu_share)
            .setContentIntent(pendingIntent)
            .build()
    }
}
