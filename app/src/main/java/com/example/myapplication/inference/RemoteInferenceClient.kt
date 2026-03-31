package com.example.myapplication.inference

import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
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
}
