package dev.gamescreen.voice.data

import dev.gamescreen.voice.domain.TranslationRepository
import kotlinx.coroutines.delay
import okhttp3.OkHttpClient
import retrofit2.HttpException
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.Body
import retrofit2.http.Header
import retrofit2.http.POST
import java.io.IOException
import java.util.concurrent.TimeUnit

/** Gson omits null fields, so source_lang = null lets DeepL auto-detect the language. */
private data class TranslateRequest(
    val text: List<String>,
    val source_lang: String?,
    val target_lang: String
)
private data class TranslateResponse(val translations: List<TranslationItem>?)
private data class TranslationItem(val text: String?)
private interface DeepLApi {
    @POST("v2/translate")
    suspend fun translate(
        @Header("Authorization") auth: String,
        @Body body: TranslateRequest
    ): TranslateResponse
}

class DeepLTranslationRepository(
    private val secrets: SecretStore
) : TranslationRepository {
    private val client = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .callTimeout(12, TimeUnit.SECONDS)
        .build()
    private val freeApi by lazy { api("https://api-free.deepl.com/") }
    private val paidApi by lazy { api("https://api.deepl.com/") }

    private fun api(url: String): DeepLApi = Retrofit.Builder()
        .baseUrl(url)
        .client(client)
        .addConverterFactory(GsonConverterFactory.create())
        .build()
        .create(DeepLApi::class.java)

    companion object {
        /** DeepL Free keys always end with ":fx"; everything else is a Pro key. */
        fun isFreeKey(key: String): Boolean = key.trim().endsWith(":fx")

        /** Source must be a bare language code ("EN", not "EN-US"); blank/AUTO = auto-detect. */
        fun normalizeSource(value: String): String? {
            val code = value.trim().uppercase().substringBefore('-')
            return code.takeIf { it.isNotEmpty() && it != "AUTO" }
        }
    }

    override suspend fun translate(text: String, sourceLanguage: String, targetLanguage: String): String {
        val key = secrets.readApiKey()?.trim()?.takeIf { it.isNotBlank() }
            ?: error("Укажите API-ключ DeepL в настройках")
        val api = if (isFreeKey(key)) freeApi else paidApi
        val request = TranslateRequest(
            listOf(text.take(1800)),
            normalizeSource(sourceLanguage),
            targetLanguage.trim().uppercase()
        )
        var attempt = 0
        while (true) {
            try {
                val result = api.translate("DeepL-Auth-Key $key", request)
                return result.translations?.firstOrNull()?.text?.takeIf { it.isNotBlank() }
                    ?: error("Пустой ответ DeepL")
            } catch (e: HttpException) {
                val code = e.code()
                // One short retry for transient overload; delay() is cancellable.
                if (attempt == 0 && (code == 429 || code == 529 || code in 500..599)) {
                    attempt++
                    delay(1500)
                    continue
                }
                val message = when (code) {
                    400 -> "DeepL: неподдерживаемый язык или неверный запрос (400)"
                    401, 403 -> if (isFreeKey(key))
                        "DeepL Free: ключ отклонён ($code)"
                    else
                        "DeepL Pro: ключ отклонён ($code). Ключ Free должен оканчиваться на :fx"
                    413 -> "DeepL: слишком длинный текст (413)"
                    429, 529 -> "DeepL: слишком много запросов ($code), повторите позже"
                    456 -> "DeepL: исчерпана квота перевода (456)"
                    in 500..599 -> "DeepL временно недоступен ($code)"
                    else -> "DeepL: HTTP $code"
                }
                throw IllegalStateException(message, e)
            } catch (e: IOException) {
                throw IOException("Нет связи с DeepL или превышено время ожидания", e)
            }
        }
    }
}
