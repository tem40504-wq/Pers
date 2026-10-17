package dev.gamescreen.voice.audio

import android.content.Context
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit
import java.util.zip.ZipInputStream

/** Small offline speech models (Vosk, ~40-50 MB each), downloaded once per language. */
object VoskModels {
    private val MODELS = mapOf(
        "en" to "vosk-model-small-en-us-0.15",
        "de" to "vosk-model-small-de-0.15",
        "fr" to "vosk-model-small-fr-0.22",
        "es" to "vosk-model-small-es-0.42",
        "it" to "vosk-model-small-it-0.22",
        "pt" to "vosk-model-small-pt-0.3",
        "zh" to "vosk-model-small-cn-0.22",
        "ja" to "vosk-model-small-ja-0.22",
        "ru" to "vosk-model-small-ru-0.22"
    )
    val supported: Set<String> get() = MODELS.keys

    private val client = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .build()

    /** "EN", "en-US", "" -> "en" (speech needs a concrete language; English by default). */
    fun languageOf(source: String): String =
        source.trim().lowercase().substringBefore('-').ifEmpty { "en" }.let { if (it == "auto") "en" else it }

    /** Returns the unpacked model folder, downloading it first if needed. Blocking: call on Dispatchers.IO. */
    fun ensure(context: Context, language: String, onStatus: (String) -> Unit): File {
        val name = MODELS[language] ?: throw IllegalArgumentException(
            "Распознавание речи для «$language» не поддерживается. Доступно: ${MODELS.keys.joinToString()}"
        )
        val root = File(context.filesDir, "vosk").apply { mkdirs() }
        val dir = File(root, name)
        val ready = File(dir, ".ready")
        if (ready.exists()) return dir

        dir.deleteRecursively()
        val zip = File(context.cacheDir, "$name.zip")
        onStatus("Загрузка модели распознавания речи (${language.uppercase()}, один раз)…")
        val request = Request.Builder().url("https://alphacephei.com/vosk/models/$name.zip").build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) throw IOException("Не удалось скачать модель речи: HTTP ${response.code}")
            val body = response.body ?: throw IOException("Пустой ответ сервера моделей")
            val total = body.contentLength()
            body.byteStream().use { input ->
                zip.outputStream().use { output ->
                    val buffer = ByteArray(64 * 1024)
                    var done = 0L
                    var lastShown = -1L
                    while (true) {
                        val n = input.read(buffer)
                        if (n < 0) break
                        output.write(buffer, 0, n)
                        done += n
                        val mb = done / (1024 * 1024)
                        if (mb != lastShown && mb % 2 == 0L) {
                            lastShown = mb
                            val of = if (total > 0) " из ${total / (1024 * 1024)}" else ""
                            onStatus("Загрузка модели речи: $mb$of МБ…")
                        }
                    }
                }
            }
        }
        onStatus("Распаковка модели речи…")
        val rootPath = root.canonicalPath + File.separator
        ZipInputStream(zip.inputStream().buffered()).use { zin ->
            while (true) {
                val entry = zin.nextEntry ?: break
                val out = File(root, entry.name)
                if (!out.canonicalPath.startsWith(rootPath)) throw IOException("Некорректный архив модели")
                if (entry.isDirectory) out.mkdirs() else {
                    out.parentFile?.mkdirs()
                    out.outputStream().use { zin.copyTo(it) }
                }
            }
        }
        zip.delete()
        if (!dir.isDirectory) throw IOException("Архив модели не содержит папку $name")
        ready.writeText("ok")
        return dir
    }
}
