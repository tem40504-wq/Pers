package org.example.gamebridge

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class StopReceiver: BroadcastReceiver() {
    override fun onReceive(context:Context,intent:Intent?) {
        // Panic из уведомления работает, даже когда открыта игра.
        AppState.stop()
        context.stopService(Intent(context,ProjectionService::class.java))
    }
}
