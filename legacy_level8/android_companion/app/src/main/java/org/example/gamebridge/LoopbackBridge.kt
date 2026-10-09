package org.example.gamebridge

import android.os.Handler
import android.os.Looper
import org.json.JSONObject
import java.net.ServerSocket
import java.net.InetAddress
import java.net.Socket
import java.io.BufferedInputStream
import java.io.ByteArrayOutputStream
import java.io.OutputStream
import java.security.MessageDigest
import java.util.Base64

/** Минимальный локальный HTTP bridge. Никогда не открывает LAN порт. */
class LoopbackBridge {
    @Volatile private var running=true
    private var server:ServerSocket?=null
    fun start() {
        Thread {
            server=ServerSocket(8766,4,InetAddress.getByName("127.0.0.1"))
            while(running) try { val socket=server!!.accept();Thread{handle(socket)}.start() }
            catch (_:Exception){if(running)AppState.stop()}
        }.apply {name="local-game-bridge";isDaemon=true;start()}
    }
    fun close(){running=false;server?.close()}
    private fun reply(out:OutputStream,code:Int,body:String){
        val bytes=body.toByteArray(Charsets.UTF_8)
        val status=if(code==200)"OK" else "Forbidden"
        val head="HTTP/1.1 $code $status\r\nContent-Type: application/json\r\nContent-Length: ${bytes.size}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n"
        out.write(head.toByteArray(Charsets.UTF_8));out.write(bytes);out.flush()
    }
    private fun readLine(stream: BufferedInputStream): String? {
        val bytes=ByteArrayOutputStream()
        while(bytes.size()<4096) {
            val c=stream.read()
            if(c<0) return null
            if(c==10) return bytes.toString("UTF-8").trimEnd('\r')
            bytes.write(c)
        }
        return null
    }
    private fun handle(socket:Socket){
        socket.use {s->
            s.soTimeout=1300
            val raw=BufferedInputStream(s.getInputStream())
            val first=readLine(raw) ?: return
            if(first.length>200)return
            val parts=first.split(' ')
            if(parts.size<2)return
            var auth="";var contentLength=0;var line:String?
            var count=0
            while(true){
                line=readLine(raw) ?: return
                if(line.isEmpty())break
                if(++count>32)return
                if(line.startsWith("Authorization:",true))auth=line.substringAfter(':').trim()
                if(line.startsWith("Content-Length:",true))contentLength=line.substringAfter(':').trim().toIntOrNull() ?: 0
            }
            val ok=MessageDigest.isEqual(auth.toByteArray(),("Bearer "+AppState.token).toByteArray())
            if(!ok){reply(s.getOutputStream(),403,"{\"error\":\"unauthorized\"}");return}
            if(contentLength>2048 || contentLength<0){reply(s.getOutputStream(),403,"{}");return}
            // GET /frame отдаёт только последний JPEG с разрешения пользователя.
            val path=parts[1]
            val response=when(path){
                "/status" -> JSONObject().put("width",AppState.width).put("height",AppState.height)
                    .put("scene","unknown").put("armed",AppState.canGesture(emptyList()))
                    .put("thermal_c",AppState.batteryTempC ?: JSONObject.NULL)
                    .put("texts",org.json.JSONArray(AppState.ocrTexts)).toString()
                "/frame" -> JSONObject().put("jpeg_b64",Base64.getEncoder().encodeToString(AppState.frame.get() ?: byteArrayOf())).toString()
                "/gesture" -> {
                    // Читаем ограниченный body; исключаем произвольное выполнение команд.
                    val body=ByteArray(contentLength)
                    var pos=0
                    while(pos<contentLength){val n=raw.read(body,pos,contentLength-pos);if(n<0)break;pos+=n}
                    try {
                        val j=JSONObject(String(body,0,pos,Charsets.UTF_8));val k=j.optString("kind")
                        val x=j.optInt("x",-1);val y=j.optInt("y",-1)
                        val x2=j.optInt("x2",-1);val y2=j.optInt("y2",-1)
                        val duration=j.optLong("duration_ms",250)
                        val points=if(k=="tap")listOf(Pair(x,y)) else listOf(Pair(x,y),Pair(x2,y2))
                        val can=(k=="tap" || k=="swipe") && AppState.canGesture(points)
                        if(can)Handler(Looper.getMainLooper()).post {
                            GameAccessibilityService.current?.gesture(k,x,y,x2,y2,duration)
                        }
                        JSONObject().put("accepted",can).toString()
                    }catch (_:Exception){"{\"accepted\":false}"}
                }
                else -> "{}"
            }
            reply(s.getOutputStream(),200,response)
        }
    }
}
