package dev.gamescreen.voice

import android.app.Application
import androidx.room.Room
import dev.gamescreen.voice.data.DeepLTranslationRepository
import dev.gamescreen.voice.data.HistoryDatabase
import dev.gamescreen.voice.data.SecretStore
import dev.gamescreen.voice.data.SettingsStore
import dev.gamescreen.voice.domain.TranslationPipeline

class GameVoiceApp : Application() {
    val settings by lazy { SettingsStore(this) }
    val secrets by lazy { SecretStore(this) }
    val database by lazy {
        Room.databaseBuilder(this, HistoryDatabase::class.java, "voice_history.db").build()
    }
    val pipeline by lazy {
        TranslationPipeline(DeepLTranslationRepository(secrets), settings, database.translations())
    }
}
