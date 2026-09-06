package com.unsafie.vpn

import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.ComponentName
import android.content.Context
import android.util.Log
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

private const val TAG = "Unsafie"
private const val UPDATE_JOB_ID = 4201
private val UPDATE_PERIOD_MS = TimeUnit.HOURS.toMillis(6)
private val UPDATE_FLEX_MS = TimeUnit.HOURS.toMillis(1)

fun scheduleUpdates(context: Context) {
    if (!updatesConfigured(BuildConfig.UPDATE_BASEURL, BuildConfig.UPDATE_TOKEN)) {
        return
    }
    val scheduler = context.getSystemService(JobScheduler::class.java) ?: return
    if (scheduler.getPendingJob(UPDATE_JOB_ID) != null) {
        return
    }
    val job =
        JobInfo
            .Builder(UPDATE_JOB_ID, ComponentName(context, UpdateJobService::class.java))
            .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
            .setPeriodic(UPDATE_PERIOD_MS, UPDATE_FLEX_MS)
            .setRequiresBatteryNotLow(true)
            .setPersisted(true)
            .build()
    try {
        if (scheduler.schedule(job) != JobScheduler.RESULT_SUCCESS) {
            Log.w(TAG, "Update: the system refused the update job")
        }
    } catch (e: Exception) {
        Log.w(TAG, "Update: failed to schedule the update job", e)
    }
}

class UpdateJobService : JobService() {
    private val executor = Executors.newSingleThreadExecutor()

    @Volatile
    private var stopped = false

    override fun onStartJob(params: JobParameters): Boolean {
        stopped = false
        executor.execute {
            val done =
                try {
                    Updater.check(applicationContext)
                } catch (e: Throwable) {
                    Log.w(TAG, "Update: the check failed", e)
                    false
                }
            if (!stopped) {
                jobFinished(params, !done)
            }
        }
        return true
    }

    override fun onStopJob(params: JobParameters): Boolean {
        stopped = true
        return true
    }

    override fun onDestroy() {
        stopped = true
        executor.shutdownNow()
        super.onDestroy()
    }
}
