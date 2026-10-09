package org.example.gamebridge

import android.app.*
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.app.PendingIntent
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.*
import java.io.ByteArrayOutputStream

class ProjectionService: Service() {
    private var projection:MediaProjection?=null
    private var display:VirtualDisplay?=null
    private var reader:ImageReader?=null
    private var server:LoopbackBridge?=null
    private var lastOcrMs=0L
    override fun onBind(intent:Intent?)=null
    override fun onCreate() {
        super.onCreate()
        val mgr=getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        mgr.createNotificationChannel(NotificationChannel("capture","Агент: захват экрана",NotificationManager.IMPORTANCE_LOW))
        val stopIntent=PendingIntent.getBroadcast(this,0,Intent(this,StopReceiver::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val notification=Notification.Builder(this,"capture")
            .setSmallIcon(android.R.drawable.ic_menu_view)
            .setContentTitle("Game Agent: захват экрана включён")
            .setOngoing(true)
            .addAction(Notification.Action.Builder(null,"PANIC STOP",stopIntent).build()).build()
        if(android.os.Build.VERSION.SDK_INT>=34) {
            startForeground(99,notification,android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        } else startForeground(99,notification)
    }
    override fun onStartCommand(intent:Intent?,flags:Int,startId:Int):Int {
        if (projection!=null)return START_NOT_STICKY
        @Suppress("DEPRECATION")
        val data=if(android.os.Build.VERSION.SDK_INT>=33)
            intent?.getParcelableExtra("projectionData",Intent::class.java)
            else intent?.getParcelableExtra<Intent>("projectionData")
        if(data==null){stopSelf();return START_NOT_STICKY}
        val code=intent.getIntExtra("resultCode",Activity.RESULT_CANCELED)
        val mgr=getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        projection=mgr.getMediaProjection(code,data)
        projection?.registerCallback(object:MediaProjection.Callback(){
            override fun onStop(){AppState.stop();stopSelf()}
        },Handler(Looper.getMainLooper()))
        val metrics=resources.displayMetrics
        val width=metrics.widthPixels; val height=metrics.heightPixels
        AppState.width=width;AppState.height=height
        reader=ImageReader.newInstance(width,height,PixelFormat.RGBA_8888,2)
        reader?.setOnImageAvailableListener({ source ->
            val img=source.acquireLatestImage() ?: return@setOnImageAvailableListener
            try {
                val plane=img.planes[0];val stride=plane.rowStride;val pixel=plane.pixelStride
                val extra=(stride-pixel*width)/pixel
                val bitmap=Bitmap.createBitmap(width+extra,height,Bitmap.Config.ARGB_8888)
                bitmap.copyPixelsFromBuffer(plane.buffer)
                val crop=Bitmap.createBitmap(bitmap,0,0,width,height)
                val out=ByteArrayOutputStream();crop.compress(Bitmap.CompressFormat.JPEG,45,out)
                AppState.frame.set(out.toByteArray())
                val battery=registerReceiver(null,IntentFilter(Intent.ACTION_BATTERY_CHANGED))
                val t=battery?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE,-1) ?: -1
                AppState.batteryTempC=if(t>=0) t/10.0 else null
                // OCR выполняется отдельно и не блокирует скриншоты.
                if(System.currentTimeMillis()-lastOcrMs>1500) {
                    lastOcrMs=System.currentTimeMillis()
                    MobileTextRecognizer.process(crop)
                }
                crop.recycle();bitmap.recycle()
            } finally {img.close()}
        },Handler(Looper.getMainLooper()))
        display=projection?.createVirtualDisplay("gamecapture",width,height,metrics.densityDpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,reader?.surface,null,null)
        server=LoopbackBridge().also{it.start()}
        return START_NOT_STICKY
    }
    override fun onDestroy(){ AppState.stop();server?.close();display?.release();reader?.close()
        projection?.stop();super.onDestroy() }
}
