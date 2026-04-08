package com.example.myapplication

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

class SpeculativeExperimentReceiver : BroadcastReceiver() {
    companion object {
        private const val TAG = "SpecExpReceiver"
    }

    override fun onReceive(context: Context, intent: Intent) {
        val pendingResult = goAsync()
        val appContext = context.applicationContext
        val baseUrl = intent.getStringExtra("baseUrl").orEmpty().ifBlank { SpeculativeExperimentRunner.DEFAULT_BASE_URL }
        val prompt = intent.getStringExtra("prompt").orEmpty().ifBlank { SpeculativeExperimentRunner.DEFAULT_PROMPT }
        val draftModelName = intent.getStringExtra("draftModelName").orEmpty().ifBlank {
            SpeculativeExperimentRunner.DRAFT_MODEL_NAME
        }
        val targetModelName = intent.getStringExtra("targetModelName").orEmpty().ifBlank {
            SpeculativeExperimentRunner.TARGET_MODEL_NAME
        }

        CoroutineScope(SupervisorJob() + Dispatchers.IO).launch {
            try {
                val summary = SpeculativeExperimentRunner.run(
                    appContext,
                    baseUrl,
                    prompt,
                    draftModelName,
                    targetModelName
                )
                val outputFile = File(appContext.filesDir, "logs/${SpeculativeExperimentRunner.OUTPUT_NAME}")
                outputFile.parentFile?.mkdirs()
                outputFile.writeText(summary)
                Log.i(TAG, summary)
            } catch (t: Throwable) {
                val failure = buildString {
                    appendLine("ANDROID_SPEC_EXPERIMENT_FAILED")
                    appendLine("error=${t::class.java.name}: ${t.message.orEmpty()}")
                    appendLine(Log.getStackTraceString(t))
                }.trim()
                val outputFile = File(appContext.filesDir, "logs/${SpeculativeExperimentRunner.OUTPUT_NAME}")
                outputFile.parentFile?.mkdirs()
                outputFile.writeText(failure)
                Log.e(TAG, failure)
            } finally {
                pendingResult.finish()
            }
        }
    }
}
