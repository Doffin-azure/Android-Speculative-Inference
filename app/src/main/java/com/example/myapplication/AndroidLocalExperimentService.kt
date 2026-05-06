package com.example.myapplication

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

class AndroidLocalExperimentService : Service() {
    companion object {
        private const val TAG = "AndroidLocalExpService"
        private const val CHANNEL_ID = "android_local_experiment"
        private const val NOTIFICATION_ID = 1002
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var wakeLock: PowerManager.WakeLock? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        val notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("Android local experiment")
            .setContentText("Running Android local model benchmark")
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
        val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = powerManager.newWakeLock(
            PowerManager.PARTIAL_WAKE_LOCK,
            "$packageName:androidLocalExperiment"
        ).apply {
            setReferenceCounted(false)
            acquire(30 * 60 * 1000L)
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val prompt = intent?.getStringExtra("prompt").orEmpty().ifBlank {
            SpeculativeExperimentRunner.DEFAULT_PROMPT
        }
        val modelName = intent?.getStringExtra("modelName").orEmpty().ifBlank {
            SpeculativeExperimentRunner.TARGET_MODEL_NAME
        }
        val maxGenerateTokens = intent?.getIntExtra(
            "maxGenerateTokens",
            SpeculativeExperimentRunner.MAX_ACCEPTED_TOKENS
        ) ?: SpeculativeExperimentRunner.MAX_ACCEPTED_TOKENS

        scope.launch {
            try {
                val summary = AndroidLocalExperimentRunner.run(
                    applicationContext,
                    prompt,
                    modelName,
                    maxGenerateTokens
                ) { progress ->
                    writeOutput(progress)
                }
                writeOutput(summary)
                Log.i(TAG, summary)
            } catch (t: Throwable) {
                val failure = buildString {
                    appendLine("ANDROID_LOCAL_EXPERIMENT_FAILED")
                    appendLine("error=${t::class.java.name}: ${t.message.orEmpty()}")
                    appendLine(Log.getStackTraceString(t))
                }.trim()
                writeOutput(failure)
                Log.e(TAG, failure)
            } finally {
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf(startId)
            }
        }

        return START_NOT_STICKY
    }

    override fun onDestroy() {
        wakeLock?.let {
            if (it.isHeld) {
                it.release()
            }
        }
        wakeLock = null
        scope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun writeOutput(text: String) {
        val outputFile = File(filesDir, "logs/${AndroidLocalExperimentRunner.OUTPUT_NAME}")
        outputFile.parentFile?.mkdirs()
        outputFile.writeText(text)
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return
        }
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Android Local Experiment",
            NotificationManager.IMPORTANCE_LOW
        )
        manager.createNotificationChannel(channel)
    }
}
