package com.unsafie.vpn

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent

const val UPDATE_CHANNEL_ID = "update_channel"
private const val UPDATE_NOTIFICATION_ID = 2

fun notifyUpdateReady(context: Context, version: String, confirm: Intent) {
    val manager = context.getSystemService(NotificationManager::class.java) ?: return

    val channel =
        NotificationChannel(
            UPDATE_CHANNEL_ID,
            context.getString(R.string.update_channel),
            NotificationManager.IMPORTANCE_LOW,
        ).apply {
            description = context.getString(R.string.update_channel_description)
            setSound(null, null)
            enableVibration(false)
            enableLights(false)
            setShowBadge(false)
        }
    manager.createNotificationChannel(channel)

    val install =
        PendingIntent.getActivity(
            context,
            0,
            Intent(confirm).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

    val notification =
        Notification
            .Builder(context, UPDATE_CHANNEL_ID)
            .setContentTitle("${context.getString(R.string.app_name)} $version")
            .setContentText(context.getString(R.string.update_ready))
            .setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setContentIntent(install)
            .setOnlyAlertOnce(true)
            .setAutoCancel(true)
            .build()

    manager.notify(UPDATE_NOTIFICATION_ID, notification)
}

fun cancelUpdateNotification(context: Context) {
    context.getSystemService(NotificationManager::class.java)?.cancel(UPDATE_NOTIFICATION_ID)
}
