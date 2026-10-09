# Архитектура 7 — Mobile + Hub

## Основа

Этот пакет содержит полную **нетронутую** доступную версию L6 в `legacy_level6/`. Пользователь сообщает, что у него уже есть L7, но его исходники/АПК не были предоставлены, поэтому миграция на конкретный неизвестный L7 выполняется через адаптеры/контракты, а не прямой патч.

```
[Android Game]
    ↓ MediaProjection (разрешение пользователя; FGS) ───────────┐
[Android Companion APK] ←─────────────────────────────────────┤
    ↕ HTTP 127.0.0.1:8766 + случайный токен                   │
[Termux Mobile Core]                                           │
   ↳ Fast loop, ~0.1 s: кадр → детекторы → Tactician → SecurityCore
   ↳ Slow loop, ~1 s: OCR/Audio/VLM/Logistic/OperatorAssistant
   ↳ SQLite память + approved JSON SkillLibrary + dead-man switch
   ↳ Android Accessibility dispatchGesture (только через APK) ┘

              Telemetry (opt-in) / Offload (opt-in)
                    ↕ ADB forward/reverse с сопряжением
[PC Windows/Linux]
   ↳ Streamlit dashboard; logcat / safe staged upload
   ↳ тяжёлый VLM за отдельным разрешением, никогда не game input
```

## Контракты совместимости

| Существующий L6/L7 | Новый адаптер | Fallback |
|---|---|---|
| Perception OpenCV/YOLO/OCR/VLM | `MobilePerception` на кадре Android Companion; нативные Android адаптеры | wait; OpenCV необязателен |
| Manager/Worker/Swarm | `TaskQueue` Commander + `Tactician`/`Logistic`; Scout в Tactician | старые модули остаются в legacy |
| Skill Library | JSON навык; только `approved:true` | `wait` |
| ChromaDB/FAISS | SQLite + косинус для малых наборов | SQLite |
| World Model/DreamerV3/EWC/GAN/ToolForge | только фоновые сервисы ПК | лёгкие эвристики / wait |
| DSL | ограниченные условные правила JSON | безопасное действие из known skill |
| HID/ADB Action | Companion Accessibility (экран Android) | **нет** fallback к АDB для игровых кликов |
| PermissionGate/SecurityCore | Y/N + Consent Android + safeRect + ARM 5 мин | stop |
| Dashboard | телефон localhost HTTP; ПК по ADB forward | консоль |

## Какие файлы меняются

- **Не меняются:** все файлы внутри `legacy_level6/`.
- **Добавляются:** `mobile_core/*.py`, `hub/*.py`, `android_companion/`, `tests/test_mobile.py`, примеры JSON и документация.
- **Для реального пользовательского L7:** требуется подставить собственные адаптеры к `Observation/Decision` и экспортировать проверенные JSON-навыки. Это не требует переписывания старого агента, но без его исходников нельзя заявить о протестированной совместимости.

## Безопасность

Termux не может напрямую выполнять Accessibility gestures или получать MediaProjection без отдельной службы/согласия. Защита **двухконтурная**:

1. `mobile_core/security.py` проверяет разрешение человека, confidence, тип, координаты и safe-zone.
2. `android_companion/AppState.kt` независимо блокирует жесты, если срок ARM истёк, нажата остановка или координаты вне заданной зоны.
3. Внешний RemoteControlServer слушает только `127.0.0.1` и принимает токен. ПК не имеет маршрута `/gesture`.
4. Функция Push Code сохраняет ZIP **без запуска/распаковки**; пользователь должен проверять и применять его вручную.
5. HMAC audit обнаруживает изменения. Для реальной цифровой подписи и шифрования требуется Android Keystore (в этой версии ещё нет криптографического хранилища ключей Android).
6. Запрет автоматических `pip install`, `apt`, загрузки APK/весов без отдельного запроса. UI Android требует отдельные разрешения системы.
7. Просмотр чужих программ/секретов запрещён. Игровые ToS должны проверяться владельцем; код не обещает anti-ban.

## Реальность модели

- ML Kit OCR: Kotlin класс с пакетом bundled; результат в /status только при работающем APK.
- YOLOv8-nano: `GameObjectDetector` adapter, веса и decode pipeline не включены — **пока не работает**.
- YAMNet: контракт AudioClassifier; нет согласованного захвата PCM и весов — **пока не работает**.
- SmolVLM-256M: `LocalSmolVLM` HTTP клиент для заранее запущенного llama.cpp; runtime, формат весов и производительность требуют проверки ARM/Termux.
- NNAPI deprecated на Android 15; TFLite GPU/CPU fallback, без фиктивной гарантии NPU.
- Термометр /status показывает **температуру батареи**, не SoC. 45°C — консервативный пример порога для battery; сигнал `PowerManager` thermal status лучше в production.
- Audio/Mic: нет фоновой записи микрофона без отдельного разрешения/FGS.
- **Функции, которых нет:** обученный DreamerV3 на Android, Falcon LLM 7B на телефоне, реальные гарантированные 10 FPS на S22 Ultra, Android APK build verification, удалённое выполнение кода.
