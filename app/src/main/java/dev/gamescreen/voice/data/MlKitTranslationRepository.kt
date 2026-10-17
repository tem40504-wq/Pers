package dev.gamescreen.voice.data

import com.google.mlkit.common.model.DownloadConditions
import com.google.mlkit.nl.languageid.LanguageIdentification
import com.google.mlkit.nl.translate.TranslateLanguage
import com.google.mlkit.nl.translate.Translation
import com.google.mlkit.nl.translate.Translator
import com.google.mlkit.nl.translate.TranslatorOptions
import dev.gamescreen.voice.domain.TranslationRepository
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.tasks.await

/**
 * Free on-device translation (Google ML Kit). No API key, no account.
 * The first use of a language pair downloads ~30 MB models; afterwards it works offline.
 */
class MlKitTranslationRepository : TranslationRepository {
    private val lock = Mutex()
    private var currentPair: Pair<String, String>? = null
    private var translator: Translator? = null
    private val readyPairs = HashSet<String>()
    private val languageId by lazy { LanguageIdentification.getClient() }

    companion object {
        /** "EN", "en-US", "PT-BR" -> ML Kit code ("en", "pt"); blank/AUTO -> null. */
        fun code(value: String): String? {
            val c = value.trim().lowercase().substringBefore('-')
            if (c.isEmpty() || c == "auto") return null
            return TranslateLanguage.fromLanguageTag(c)
        }
    }

    override fun label(): String = "офлайн"

    override suspend fun translate(
        text: String,
        sourceLanguage: String,
        targetLanguage: String,
        onStatus: (String) -> Unit
    ): String {
        val target = code(targetLanguage)
            ?: error("Офлайн-перевод не поддерживает язык «$targetLanguage»")
        val source = if (sourceLanguage.isBlank() || sourceLanguage.equals("AUTO", true)) detect(text)
            else code(sourceLanguage) ?: error("Офлайн-перевод не поддерживает язык «$sourceLanguage»")
        if (source == target) return text
        return lock.withLock {
            val t = translatorFor(source, target)
            val pair = "$source>$target"
            if (pair !in readyPairs) {
                onStatus("Загрузка языковой модели ${source.uppercase()}→${target.uppercase()} (~30 МБ, один раз)…")
                try {
                    t.downloadModelIfNeeded(DownloadConditions.Builder().build()).await()
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    throw IllegalStateException(
                        "Не удалось загрузить языковую модель: нужен интернет и сервисы Google Play", e)
                }
                readyPairs += pair
                onStatus("Перевод...")
            }
            t.translate(text).await()
        }
    }

    private suspend fun detect(text: String): String {
        val tag = try { languageId.identifyLanguage(text).await() } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) { "und" }
        return (if (tag == "und") null else TranslateLanguage.fromLanguageTag(tag.substringBefore('-')))
            ?: error("Не удалось определить язык текста — укажите его в поле «Из»")
    }

    private fun translatorFor(source: String, target: String): Translator {
        if (currentPair == (source to target)) translator?.let { return it }
        translator?.close()
        val created = Translation.getClient(
            TranslatorOptions.Builder().setSourceLanguage(source).setTargetLanguage(target).build()
        )
        translator = created
        currentPair = source to target
        return created
    }
}
