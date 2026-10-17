# Extension samples (not compiled into MVP)

- `OcrEngine.kt`: ML Kit Latin OCR on Bitmap. To capture external app's frames, request MediaProjection consent and create ImageReader/VirtualDisplay on a `mediaProjection` FGS. Always crop the selected region, close each Image and throttle OCR.
- `STTManager.kt`: SpeechRecognizer for microphone; not a streaming PCM decoder, not a way to transcribe audio from a game's AudioRecord. Use Vosk, Whisper or remote streaming transcription for AudioPlaybackCapture PCM.
- `AudioPlaybackCaptureSample.kt`: legal platform API for opt-in audio capture. Works only when the source app permits capturing. Close AudioRecord and MediaProjection after use. Register MediaProjection.Callback before createVirtualDisplay. Android 14+ requires one user-consent token per projection session.

Manifest additions for phase2/3 (not for MVP):
```
<uses-permission android:name="android.permission.FOREGROUND_SERVICE_MEDIA_PROJECTION" />
<uses-permission android:name="android.permission.RECORD_AUDIO" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE_MICROPHONE" />
<queries><intent><action android:name="android.speech.RecognitionService" /></intent></queries>
```
The MediaProjection service must use `android:foregroundServiceType="mediaProjection"`; microphone foreground recording requires `microphone`. Start from visible Activity; request MediaProjection with `MediaProjectionManager.createScreenCaptureIntent()`, then after consent start FGS, then call getMediaProjection. If recording both screen and microphone, follow FGS type and runtime permission requirements for each feature. Never silently restart capture after process death.
