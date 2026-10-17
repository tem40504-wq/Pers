package dev.gamescreen.voice.domain

import android.os.SystemClock
import dev.gamescreen.voice.data.SettingsStore
import dev.gamescreen.voice.data.TranslationDao
import dev.gamescreen.voice.data.TranslationRecord
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull

private data class Captured(val packageName: String, val text: String)
data class TranslationState(
    val original: String = "",
    val translated: String = "",
    val status: String = "Ожидание текста"
)

/**
 * 0.1.2 processing model:
 *  - debounce with an upper bound (maxWait): constantly changing UI no longer starves translation;
 *  - translations run sequentially, the newest pending capture replaces older ones (CONFLATED),
 *    so a stale result can never overwrite a newer one and an in-flight request is not thrown away;
 *  - identical text is not re-sent, but after an error the same text is retried (not more often than every 5 s).
 */
class TranslationPipeline(
    private val repository: TranslationRepository,
    private val settings: SettingsStore,
    private val dao: TranslationDao
) {
    companion object {
        private const val DEMO_TEXT = "Hello world. This is a translation test."
        private const val RETRY_AFTER_ERROR_MS = 5_000L
        private const val MAX_EXTRA_WAIT_MS = 1_500L
    }

    @Volatile var isEnabled = false
        private set
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val events = Channel<Captured>(Channel.CONFLATED)
    private val mutableState = MutableStateFlow(TranslationState())
    val state: StateFlow<TranslationState> = mutableState.asStateFlow()
    private var job: Job? = null
    private var preview: Job? = null

    // Dedupe state for submit(): written on the main thread and the worker, hence @Volatile.
    @Volatile private var lastSubmittedKey: String? = null
    @Volatile private var retryAllowedAt = Long.MAX_VALUE

    // Temporary bounded RAM cache: no disk persistence when history is disabled.
    private val memoryCache = object : LinkedHashMap<String, String>(128, .75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, String>?): Boolean =
            size > 128
    }
    private val cacheLock = Any()
    private fun key(text: String, source: String, target: String): String =
        "$source\u0000$target\u0000$text"

    fun start() {
        if (isEnabled) return
        preview?.cancel()
        preview = null
        while (events.tryReceive().isSuccess) { /* drop captures left from a previous session */ }
        lastSubmittedKey = null
        retryAllowedAt = Long.MAX_VALUE
        isEnabled = true
        mutableState.value = TranslationState(status = "Ожидание текста выбранного приложения")
        job = scope.launch { loop() }
    }

    private suspend fun loop() {
        while (true) { // cancelled through events.receive()
            var latest = events.receive()
            val quiet = settings.load().delayMs.coerceIn(200, 2500)
            val deadline = SystemClock.elapsedRealtime() + quiet + MAX_EXTRA_WAIT_MS
            // Wait for a quiet period, but never longer than `deadline`.
            while (true) {
                val wait = minOf(quiet, deadline - SystemClock.elapsedRealtime())
                if (wait <= 0) break
                latest = withTimeoutOrNull(wait) { events.receive() } ?: break
            }
            if (!isEnabled) continue
            process(latest)
        }
    }

    private suspend fun process(capture: Captured, demo: Boolean = false) {
        val s = settings.load()
        val source = s.sourceLang.trim().uppercase()
        val target = s.targetLang.trim().uppercase()
        val cacheKey = key(capture.text, source, target)
        mutableState.value = TranslationState(capture.text, "", "Перевод...")
        try {
            // The test always reaches DeepL, so a changed/invalid key is not hidden by the cache.
            val cached = if (demo) null else synchronized(cacheLock) { memoryCache[cacheKey] }
            val result = cached ?: withContext(Dispatchers.IO) {
                (if (s.keepHistory && !demo) dao.cached(capture.text, source, target) else null)
                    ?: repository.translate(capture.text, source, target).also { translation ->
                        if (s.keepHistory && !demo) {
                            dao.insert(TranslationRecord(
                                packageName = capture.packageName,
                                original = capture.text, translated = translation,
                                sourceLang = source, targetLang = target
                            ))
                        }
                    }
            }
            synchronized(cacheLock) { memoryCache[cacheKey] = result }
            mutableState.value = TranslationState(capture.text, result, if (demo) "Тест пройден" else "Готово")
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            if (!demo && lastSubmittedKey == cacheKey) {
                retryAllowedAt = SystemClock.elapsedRealtime() + RETRY_AFTER_ERROR_MS
            }
            mutableState.value = TranslationState(
                capture.text, "", "Ошибка: ${e.message.orEmpty().take(115)}"
            )
        }
    }

    fun submit(packageName: String, text: String) {
        if (!isEnabled) return
        val clean = text.trim().take(1400)
        if (clean.isEmpty()) return
        val s = settings.load()
        val k = key(clean, s.sourceLang.trim().uppercase(), s.targetLang.trim().uppercase())
        // Same text (and same languages) as last time: skip, unless the last attempt failed long enough ago.
        if (k == lastSubmittedKey && SystemClock.elapsedRealtime() < retryAllowedAt) return
        lastSubmittedKey = k
        retryAllowedAt = Long.MAX_VALUE
        events.trySend(Captured(packageName, clean))
    }

    /** Works with or without overlay/Accessibility; every press really calls the translator. */
    fun testTranslation() {
        preview?.cancel()
        preview = scope.launch { process(Captured("demo", DEMO_TEXT), demo = true) }
    }

    fun stop() {
        isEnabled = false
        job?.cancel()
        job = null
        preview?.cancel()
        preview = null
        while (events.tryReceive().isSuccess) { }
        synchronized(cacheLock) { memoryCache.clear() }
        mutableState.value = TranslationState(status = "Остановлено")
    }

    fun clearMemoryCache() { synchronized(cacheLock) { memoryCache.clear() } }
    fun close() { stop(); scope.cancel() }
}
