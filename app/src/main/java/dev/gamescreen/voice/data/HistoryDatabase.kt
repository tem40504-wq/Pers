package dev.gamescreen.voice.data

import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.RoomDatabase
import kotlinx.coroutines.flow.Flow

@Entity(tableName = "translations")
data class TranslationRecord(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val packageName: String,
    val original: String,
    val translated: String,
    val sourceLang: String,
    val targetLang: String,
    val timestamp: Long = System.currentTimeMillis()
)

@Dao
interface TranslationDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(record: TranslationRecord)

    @Query("SELECT translated FROM translations WHERE original = :text AND sourceLang = :source AND targetLang = :target ORDER BY timestamp DESC LIMIT 1")
    suspend fun cached(text: String, source: String, target: String): String?

    @Query("SELECT * FROM translations ORDER BY timestamp DESC LIMIT 100")
    fun latest(): Flow<List<TranslationRecord>>

    @Query("DELETE FROM translations")
    suspend fun clear()
}

@Database(entities = [TranslationRecord::class], version = 1, exportSchema = false)
abstract class HistoryDatabase : RoomDatabase() {
    abstract fun translations(): TranslationDao
}
