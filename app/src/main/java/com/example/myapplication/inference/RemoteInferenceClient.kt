package com.example.myapplication.inference

import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

data class RemoteGenerateRequest(
    val requestId: String = UUID.randomUUID().toString(),
    val model: String = "",
    val systemPrompt: String = "",
    val userPrompt: String,
    val maxTokens: Int = 64,
    val temperature: Double = 0.7,
    val topP: Double = 0.9
)

data class RemoteGenerateResponse(
    val requestId: String,
    val outputText: String,
    val finishReason: String,
    val backendLabel: String,
    val error: String,
    val generationMs: Long
)

data class RemoteProbeResponse(
    val status: String,
    val message: String,
    val clientAddress: String,
    val requestLogPath: String,
    val ipv4Addresses: List<String>
)

data class SpeculativeStartRequest(
    val protocolVersion: Int = 1,
    val sessionId: String = UUID.randomUUID().toString(),
    val requestId: String = UUID.randomUUID().toString(),
    val draftModel: String = "android-draft-stub",
    val targetModel: String = "desktop-target",
    val systemPrompt: String = "",
    val userPrompt: String,
    val temperature: Double = 0.7,
    val topP: Double = 0.9
)

data class SpeculativeStartResponse(
    val sessionId: String,
    val requestId: String,
    val status: String,
    val fallbackAvailable: Boolean,
    val error: String
)

data class SpeculativeProposeRequest(
    val protocolVersion: Int = 1,
    val sessionId: String,
    val draftStep: Int,
    val proposedTokenIds: List<Int>,
    val proposedText: String,
    val maxCorrectionTokens: Int = 1
)

data class SpeculativeProposeResponse(
    val sessionId: String,
    val requestId: String,
    val status: String,
    val acceptedCount: Int,
    val acceptedTokenIds: List<Int>,
    val rejectedFromIndex: Int,
    val correctionTokenIds: List<Int>,
    val targetTextDelta: String,
    val warning: String,
    val finishReason: String,
    val error: String
)

data class SpeculativeCloseRequest(
    val protocolVersion: Int = 1,
    val sessionId: String,
    val reason: String = "completed"
)

data class SpeculativeCloseResponse(
    val sessionId: String,
    val status: String,
    val reason: String,
    val acceptedTokenCount: Int,
    val mismatchCount: Int,
    val lastFinishReason: String,
    val error: String
)

class RemoteInferenceClient {
    suspend fun health(baseUrl: String): String = withContext(Dispatchers.IO) {
        val connection = openJsonConnection(baseUrl.trimEnd('/') + "/health", "GET")
        try {
            val statusCode = connection.responseCode
            val body = readResponseBody(connection, statusCode)
            require(statusCode in 200..299) { "Health check failed: HTTP $statusCode ${body.ifBlank { "" }}".trim() }
            JSONObject(body).optString("status", "unknown")
        } finally {
            connection.disconnect()
        }
    }

    suspend fun probe(baseUrl: String): RemoteProbeResponse = withContext(Dispatchers.IO) {
        val connection = openJsonConnection(baseUrl.trimEnd('/') + "/probe", "GET")
        try {
            val statusCode = connection.responseCode
            val body = readResponseBody(connection, statusCode)
            require(statusCode in 200..299) { "Probe failed: HTTP $statusCode ${body.ifBlank { "" }}".trim() }
            val json = JSONObject(body)
            val addressArray = json.optJSONArray("ipv4Addresses")
            val addresses = buildList {
                if (addressArray != null) {
                    for (index in 0 until addressArray.length()) {
                        add(addressArray.optString(index))
                    }
                }
            }
            RemoteProbeResponse(
                status = json.optString("status", "unknown"),
                message = json.optString("message"),
                clientAddress = json.optString("clientAddress"),
                requestLogPath = json.optString("requestLogPath"),
                ipv4Addresses = addresses
            )
        } finally {
            connection.disconnect()
        }
    }

    suspend fun generate(baseUrl: String, request: RemoteGenerateRequest): RemoteGenerateResponse =
        withContext(Dispatchers.IO) {
            val connection = openJsonConnection(baseUrl.trimEnd('/') + "/v1/generate", "POST")
            val payload = JSONObject().apply {
                put("requestId", request.requestId)
                put("model", request.model)
                put("systemPrompt", request.systemPrompt)
                put("userPrompt", request.userPrompt)
                put("maxTokens", request.maxTokens)
                put("temperature", request.temperature)
                put("topP", request.topP)
            }

            try {
                OutputStreamWriter(connection.outputStream, Charsets.UTF_8).use { writer ->
                    writer.write(payload.toString())
                }

                val statusCode = connection.responseCode
                val body = readResponseBody(connection, statusCode)
                val json = JSONObject(body)
                val error = json.optString("error")
                require(statusCode in 200..299) {
                    "Remote inference failed: HTTP $statusCode ${error.ifBlank { body }}"
                }

                RemoteGenerateResponse(
                    requestId = json.optString("requestId", request.requestId),
                    outputText = json.optString("outputText"),
                    finishReason = json.optString("finishReason", "unknown"),
                    backendLabel = json.optString("backendLabel", "remote"),
                    error = error,
                    generationMs = json.optJSONObject("timings")?.optLong("generationMs") ?: -1L
                )
            } finally {
                connection.disconnect()
            }
        }

    suspend fun startSpeculativeSession(
        baseUrl: String,
        request: SpeculativeStartRequest
    ): SpeculativeStartResponse = withContext(Dispatchers.IO) {
        val connection = openJsonConnection(baseUrl.trimEnd('/') + "/v1/speculative/start", "POST")
        val payload = JSONObject().apply {
            put("protocolVersion", request.protocolVersion)
            put("type", "startSession")
            put("sessionId", request.sessionId)
            put("requestId", request.requestId)
            put("draftModel", request.draftModel)
            put("targetModel", request.targetModel)
            put("systemPrompt", request.systemPrompt)
            put("userPrompt", request.userPrompt)
            put(
                "sampling",
                JSONObject().apply {
                    put("temperature", request.temperature)
                    put("topP", request.topP)
                }
            )
        }

        try {
            OutputStreamWriter(connection.outputStream, Charsets.UTF_8).use { writer ->
                writer.write(payload.toString())
            }

            val statusCode = connection.responseCode
            val body = readResponseBody(connection, statusCode)
            val json = JSONObject(body)
            val error = json.optString("error")
            require(statusCode in 200..299) {
                "Speculative start failed: HTTP $statusCode ${error.ifBlank { body }}"
            }

            SpeculativeStartResponse(
                sessionId = json.optString("sessionId", request.sessionId),
                requestId = json.optString("requestId", request.requestId),
                status = json.optString("status", "unknown"),
                fallbackAvailable = json.optBoolean("fallbackAvailable", false),
                error = error
            )
        } finally {
            connection.disconnect()
        }
    }

    suspend fun proposeDraft(
        baseUrl: String,
        request: SpeculativeProposeRequest
    ): SpeculativeProposeResponse = withContext(Dispatchers.IO) {
        val connection = openJsonConnection(baseUrl.trimEnd('/') + "/v1/speculative/propose", "POST")
        val payload = JSONObject().apply {
            put("protocolVersion", request.protocolVersion)
            put("type", "proposeDraft")
            put("sessionId", request.sessionId)
            put("draftStep", request.draftStep)
            put("proposedTokenIds", JSONArray(request.proposedTokenIds))
            put("proposedText", request.proposedText)
            put("maxCorrectionTokens", request.maxCorrectionTokens)
        }

        try {
            OutputStreamWriter(connection.outputStream, Charsets.UTF_8).use { writer ->
                writer.write(payload.toString())
            }

            val statusCode = connection.responseCode
            val body = readResponseBody(connection, statusCode)
            val json = JSONObject(body)
            val error = json.optString("error")
            require(statusCode in 200..299) {
                "Speculative propose failed: HTTP $statusCode ${error.ifBlank { body }}"
            }

            SpeculativeProposeResponse(
                sessionId = json.optString("sessionId", request.sessionId),
                requestId = json.optString("requestId"),
                status = json.optString("status", "unknown"),
                acceptedCount = json.optInt("acceptedCount", 0),
                acceptedTokenIds = json.optJSONArray("acceptedTokenIds").toIntList(),
                rejectedFromIndex = json.optInt("rejectedFromIndex", -1),
                correctionTokenIds = json.optJSONArray("correctionTokenIds").toIntList(),
                targetTextDelta = json.optString("targetTextDelta"),
                warning = json.optString("warning"),
                finishReason = json.optString("finishReason"),
                error = error
            )
        } finally {
            connection.disconnect()
        }
    }

    suspend fun closeSpeculativeSession(
        baseUrl: String,
        request: SpeculativeCloseRequest
    ): SpeculativeCloseResponse = withContext(Dispatchers.IO) {
        val connection = openJsonConnection(baseUrl.trimEnd('/') + "/v1/speculative/close", "POST")
        val payload = JSONObject().apply {
            put("protocolVersion", request.protocolVersion)
            put("type", "closeSession")
            put("sessionId", request.sessionId)
            put("reason", request.reason)
        }

        try {
            OutputStreamWriter(connection.outputStream, Charsets.UTF_8).use { writer ->
                writer.write(payload.toString())
            }

            val statusCode = connection.responseCode
            val body = readResponseBody(connection, statusCode)
            val json = JSONObject(body)
            val error = json.optString("error")
            require(statusCode in 200..299) {
                "Speculative close failed: HTTP $statusCode ${error.ifBlank { body }}"
            }

            SpeculativeCloseResponse(
                sessionId = json.optString("sessionId", request.sessionId),
                status = json.optString("status", "unknown"),
                reason = json.optString("reason", request.reason),
                acceptedTokenCount = json.optInt("acceptedTokenCount", 0),
                mismatchCount = json.optInt("mismatchCount", 0),
                lastFinishReason = json.optString("lastFinishReason"),
                error = error
            )
        } finally {
            connection.disconnect()
        }
    }

    private fun openJsonConnection(url: String, method: String): HttpURLConnection {
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.requestMethod = method
        connection.connectTimeout = 10_000
        connection.readTimeout = 180_000
        connection.setRequestProperty("Accept", "application/json")
        if (method == "POST") {
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
        }
        return connection
    }

    private fun readResponseBody(connection: HttpURLConnection, statusCode: Int): String {
        val stream = if (statusCode in 200..299) {
            connection.inputStream
        } else {
            connection.errorStream ?: connection.inputStream
        }

        BufferedReader(InputStreamReader(stream, Charsets.UTF_8)).use { reader ->
            return reader.readText()
        }
    }

    private fun JSONArray?.toIntList(): List<Int> = buildList {
        if (this@toIntList == null) {
            return@buildList
        }
        for (index in 0 until this@toIntList.length()) {
            add(this@toIntList.optInt(index))
        }
    }
}
