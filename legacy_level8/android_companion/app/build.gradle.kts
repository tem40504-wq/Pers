plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
android {
    namespace = "org.example.gamebridge"
    compileSdk = 35
    defaultConfig { applicationId = "org.example.gamebridge"; minSdk = 29; targetSdk = 35; versionCode = 1; versionName = "0.1-source" }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
}

// Модель ML Kit поставляется в APK; скачивание Gradle-зависимостей —
// только при осознанной сборке владельцем. Тяжёлые веса не загружаются автоматически.
dependencies { implementation("com.google.mlkit:text-recognition:16.0.1") }
