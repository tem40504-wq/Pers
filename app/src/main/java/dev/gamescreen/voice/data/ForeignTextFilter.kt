package dev.gamescreen.voice.data

import com.google.mlkit.nl.languageid.LanguageIdentification
import com.google.mlkit.nl.languageid.LanguageIdentificationOptions
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.tasks.await

/** On-device language ID: keeps only lines that are NOT already in the target language. */
class ForeignTextFilter {
    private val identifier by lazy {
        LanguageIdentification.getClient(
            LanguageIdentificationOptions.Builder().setConfidenceThreshold(0.5f).build()
        )
    }

    suspend fun keepForeign(text: String, target: String): String {
        val t = target.trim().lowercase().substringBefore('-')
        return text.lines().map { it.trim() }.filter { line ->
            if (line.length < 2 || line.none { it.isLetter() }) return@filter false
            // Handles like "@Channel_Name" are not worth translating.
            if (line.startsWith("@") && !line.contains(' ')) return@filter false
            if (looksLikeScript(line, t)) return@filter false
            val lang = try { identifier.identifyLanguage(line).await() } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) { "und" }
            lang == "und" || lang.substringBefore('-') != t
        }.joinToString("\n")
    }

    /** Cheap pre-check for Cyrillic targets: a line written mostly in Cyrillic is already "ours". */
    private fun looksLikeScript(line: String, target: String): Boolean {
        if (target !in setOf("ru", "uk", "be", "bg", "sr", "kk")) return false
        val letters = line.filter { it.isLetter() }
        if (letters.isEmpty()) return false
        val cyr = letters.count { Character.UnicodeBlock.of(it) == Character.UnicodeBlock.CYRILLIC }
        return cyr * 2 > letters.length
    }
}
