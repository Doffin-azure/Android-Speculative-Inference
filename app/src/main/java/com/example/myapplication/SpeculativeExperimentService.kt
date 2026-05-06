package com.example.myapplication

import android.app.Notification
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

class SpeculativeExperimentService : Service() {
    companion object {
        private const val TAG = "SpecExpService"
        private const val CHANNEL_ID = "speculative_experiment"
        private const val NOTIFICATION_ID = 1001
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var wakeLock: PowerManager.WakeLock? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        val notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("Speculative experiment")
            .setContentText("Running Android speculative benchmark")
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
            "$packageName:speculativeExperiment"
        ).apply {
            setReferenceCounted(false)
            acquire(30 * 60 * 1000L)
        }
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
        val maxAcceptedTokens = intent?.getIntExtra(
            "maxAcceptedTokens",
            SpeculativeExperimentRunner.MAX_ACCEPTED_TOKENS
        ) ?: SpeculativeExperimentRunner.MAX_ACCEPTED_TOKENS
        val draftMaxTokens = intent?.getIntExtra("draftMaxTokens", SpeculativeExperimentRunner.DRAFT_MAX_TOKENS)
            ?: SpeculativeExperimentRunner.DRAFT_MAX_TOKENS
        val initialDraftTokens = intent?.getIntExtra("initialDraftTokens", draftMaxTokens)
            ?: draftMaxTokens
        val draftMinTokens = intent?.getIntExtra("draftMinTokens", SpeculativeExperimentRunner.DRAFT_MIN_TOKENS)
            ?: SpeculativeExperimentRunner.DRAFT_MIN_TOKENS
        val draftMinProb = if (intent?.hasExtra("draftMinProb") == true) {
            intent.getFloatExtra(
                "draftMinProb",
                SpeculativeExperimentRunner.DRAFT_MIN_PROB_UNSUPPORTED.toFloat()
            ).toDouble()
        } else {
            SpeculativeExperimentRunner.DRAFT_MIN_PROB_UNSUPPORTED
        }
        val adaptiveDraftingEnabled = intent?.getBooleanExtra("adaptiveDraftingEnabled", false) ?: false
        val adaptiveDraftMinTokens = intent?.getIntExtra(
            "adaptiveDraftMinTokens",
            SpeculativeExperimentRunner.ADAPTIVE_DRAFT_MIN_TOKENS
        ) ?: SpeculativeExperimentRunner.ADAPTIVE_DRAFT_MIN_TOKENS

        scope.launch {
            try {
                val summary = SpeculativeExperimentRunner.run(
                    applicationContext,
                    baseUrl,
                    prompt,
                    draftModelName,
                    targetModelName,
                    maxAcceptedTokens = maxAcceptedTokens,
                    draftMaxTokens = draftMaxTokens,
                    initialDraftTokens = initialDraftTokens,
                    draftMinTokens = draftMinTokens,
                    draftMinProb = draftMinProb,
                    adaptiveDraftingEnabled = adaptiveDraftingEnabled,
                    adaptiveDraftMinTokens = adaptiveDraftMinTokens,
                    onProgress = { progress ->
                        writeOutput(progress)
                    }
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
