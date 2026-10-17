// PHASE 3 SAMPLE — NOT INCLUDED IN MVP BUILD.
// Call AFTER user-granted MediaProjection token and mediaProjection foreground service startup.
package dev.gamescreen.voice.phase2

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioPlaybackCaptureConfiguration
import android.media.AudioRecord
import android.media.projection.MediaProjection

fun startPlaybackCapture(projection: MediaProjection): AudioRecord {
    val capture = AudioPlaybackCaptureConfiguration.Builder(projection)
        .addMatchingUsage(AudioAttributes.USAGE_GAME)
        .addMatchingUsage(AudioAttributes.USAGE_MEDIA)
        .build()
    val format = AudioFormat.Builder()
        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
        .setSampleRate(16000)
        .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
        .build()
    val minBuffer = AudioRecord.getMinBufferSize(16000,
        AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
    require(minBuffer > 0)
    return AudioRecord.Builder()
        .setAudioFormat(format)
        .setBufferSizeInBytes(minBuffer * 4)
        .setAudioPlaybackCaptureConfig(capture)
        .build().also { record ->
            check(record.state == AudioRecord.STATE_INITIALIZED)
            record.startRecording()
        }
}
