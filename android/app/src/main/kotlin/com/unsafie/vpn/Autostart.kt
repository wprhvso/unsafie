package com.unsafie.vpn

import android.content.Context

internal const val PREFS = "unsafie"
private const val KEY_AUTOSTART = "autostart"

fun autostartEnabled(context: Context): Boolean =
    context
        .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .getBoolean(KEY_AUTOSTART, true)

fun rememberAutostart(context: Context, enabled: Boolean) {
    context
        .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .edit()
        .putBoolean(KEY_AUTOSTART, enabled)
        .apply()
}
