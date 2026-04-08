package com.example.myapplication

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

class SpeculativeExperimentService : Service() {
    companion object {
        private const val TAG = "SpecExpService"
        private const val CHANNEL_ID = "speculative_experiment"
        private const val NOTIFICATION_ID = 1001
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        startForeground(
            NOTIFICATION_ID,
            NotificationCompat.Builder(this, CHANNEL_ID)
                .setSmallIcon(R.mipmap.ic_launcher)
                .setContentTitle("Speculative experiment")
                .setContentText("Running Android speculative benchmark")
                .setOngoing(true)
                .build()
        )
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val baseUrl = intent?.getStringExtra("baseUrl").orEmpty().ifBlank {
            SpeculativeExperimentRunner.DEFAULT_BASE_URL
        }
        val prompt = intent?.getStringExtra("prompt").orEmpty().ifBlank {
            SpeculativeExperimentRunner.DEFAULT_PROMPT
        }
        val draftModelName = intent?.getStringExtra("draftModelName").orEmpty().ifBlank {
            SpeculativeExperimentRunner.DRAFT_MODEL_NAME
        }
        val targetModelName = intent?.getStringExtra("targetModelName").orEmpty().ifBlank {
            SpeculativeExperimentRunner.TARGET_MODEL_NAME
        }

        scope.launch {
            try {
                val summary = SpeculativeExperimentRunner.run(
                    applicationContext,
                    baseUrl,
                    prompt,
                    draftModelName,
                    targetModelName
                )
                writeOutput(summary)
                Log.i(TAG, summary)
            } catch (t: Throwable) {
                val failure = buildString {
                    appendLine("ANDROID_SPEC_EXPERIMENT_FAILED")
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
        scope.cancel()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun writeOutput(text: String) {
        val outputFile = File(filesDir, "logs/${SpeculativeExperimentRunner.OUTPUT_NAME}")
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
            "Speculative Experiment",
            NotificationManager.IMPORTANCE_LOW
        )
        manager.createNotificationChannel(channel)
    }
}
