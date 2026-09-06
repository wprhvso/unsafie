package com.unsafie.vpn

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.os.Build
import android.util.Log
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URI
import org.json.JSONException
import org.json.JSONObject

private const val TAG = "Unsafie"
private const val KEY_STAGED = "staged_update"
private const val KEY_STAGED_SESSION = "staged_session"
private const val APK_ENTRY = "unsafie.apk"
private const val CONNECT_TIMEOUT_MS = 15_000
private const val READ_TIMEOUT_MS = 60_000
private const val COPY_BUFFER = 64 * 1024

object Updater {
    fun check(context: Context): Boolean {
        val base = BuildConfig.UPDATE_BASEURL
        if (!updatesConfigured(base, BuildConfig.UPDATE_TOKEN)) {
            return true
        }
        val abis = Build.SUPPORTED_ABIS?.toList().orEmpty()
        val abi = updateAbi(abis)
        if (abi == null) {
            Log.i(TAG, "Update: no release is built for ${abis.joinToString()}")
            return true
        }

        val version = published(base) ?: return false
        if (!isNewerVersion(BuildConfig.VERSION_NAME, version)) {
            forgetStaged(context)
            return true
        }
        if (stagedVersion(context) == version && stagedSessionAlive(context)) {
            Log.i(TAG, "Update: $version is already waiting to be installed")
            return true
        }
        return stage(context, version, updateApkUrl(base, version, abi))
    }

    private fun published(base: String): String? {
        val connection = open(base) ?: return null
        try {
            if (connection.responseCode == HttpURLConnection.HTTP_NOT_FOUND) {
                return ""
            }
            if (connection.responseCode != HttpURLConnection.HTTP_OK) {
                Log.w(TAG, "Update: the manifest answered ${connection.responseCode}")
                return null
            }
            val body = connection.inputStream.bufferedReader().use { it.readText() }
            return JSONObject(body).optString("version")
        } catch (e: IOException) {
            Log.w(TAG, "Update: the manifest is unreachable", e)
            return null
        } catch (e: JSONException) {
            Log.w(TAG, "Update: the manifest is not JSON", e)
            return null
        } finally {
            connection.disconnect()
        }
    }

    private fun stage(context: Context, version: String, url: String): Boolean {
        val installer = context.packageManager.packageInstaller
        val params =
            PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL).apply {
                setAppPackageName(context.packageName)
            }

        val sessionId =
            try {
                installer.createSession(params)
            } catch (e: IOException) {
                Log.w(TAG, "Update: cannot open an install session", e)
                return false
            }

        return try {
            installer.openSession(sessionId).use { session ->
                download(url, session)
                rememberStaged(context, version, sessionId)
                session.commit(installStatus(context, version, sessionId).intentSender)
            }
            Log.i(TAG, "Update: $version is downloaded and waiting for a tap")
            true
        } catch (e: IOException) {
            Log.w(TAG, "Update: $version failed to download", e)
            installer.abandonSession(sessionId)
            forgetStaged(context)
            false
        }
    }

    private fun download(url: String, session: PackageInstaller.Session) {
        val connection = open(url) ?: throw IOException("cannot reach $url")
        try {
            if (connection.responseCode != HttpURLConnection.HTTP_OK) {
                throw IOException("the release answered ${connection.responseCode}")
            }
            session.openWrite(APK_ENTRY, 0, connection.contentLengthLong).use { sink ->
                connection.inputStream.use { source -> source.copyTo(sink, COPY_BUFFER) }
                session.fsync(sink)
            }
        } finally {
            connection.disconnect()
        }
    }

    private fun open(url: String): HttpURLConnection? =
        try {
            (URI.create(url).toURL().openConnection() as HttpURLConnection).apply {
                connectTimeout = CONNECT_TIMEOUT_MS
                readTimeout = READ_TIMEOUT_MS
                instanceFollowRedirects = true
                setRequestProperty("Accept-Encoding", "identity")
                setRequestProperty("Authorization", "Bearer ${BuildConfig.UPDATE_TOKEN}")
            }
        } catch (e: IOException) {
            Log.w(TAG, "Update: cannot open $url", e)
            null
        } catch (e: IllegalArgumentException) {
            Log.w(TAG, "Update: $url is not a URL", e)
            null
        }

    private fun stagedSessionAlive(context: Context): Boolean {
        val id =
            context
                .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getInt(KEY_STAGED_SESSION, -1)
        return id >= 0 && context.packageManager.packageInstaller.getSessionInfo(id) != null
    }

    private fun installStatus(context: Context, version: String, sessionId: Int) =
        PendingIntent.getBroadcast(
            context,
            sessionId,
            Intent(context, UpdateInstallReceiver::class.java)
                .setAction(UpdateInstallReceiver.ACTION_STATUS)
                .putExtra(UpdateInstallReceiver.EXTRA_VERSION, version),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE,
        )
}

fun stagedVersion(context: Context): String? =
    context
        .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .getString(KEY_STAGED, null)

fun rememberStaged(context: Context, version: String, sessionId: Int) {
    context
        .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .edit()
        .putString(KEY_STAGED, version)
        .putInt(KEY_STAGED_SESSION, sessionId)
        .apply()
}

fun forgetStaged(context: Context) {
    context
        .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .edit()
        .remove(KEY_STAGED)
        .remove(KEY_STAGED_SESSION)
        .apply()
}
