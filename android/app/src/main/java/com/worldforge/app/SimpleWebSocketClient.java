package com.worldforge.app;

import android.util.Base64;
import org.json.JSONObject;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import javax.net.ssl.SSLSocketFactory;

public final class SimpleWebSocketClient {
    public interface Listener { void onOpen(); void onMessage(JSONObject message); void onClosed(); void onError(Exception error); }
    private final String url; private final Listener listener; private volatile boolean running; private Socket socket; private InputStream in; private OutputStream out;
    private final SecureRandom random = new SecureRandom();
    public SimpleWebSocketClient(String url, Listener listener){this.url=url;this.listener=listener;}

    public void connect(){new Thread(() -> {try{run();}catch(Exception e){if(running)listener.onError(e);}finally{running=false;closeQuiet();listener.onClosed();}},"worldforge-ws").start();}
    private void run() throws Exception {
        URI u=URI.create(url); boolean secure="wss".equalsIgnoreCase(u.getScheme()); int port=u.getPort()>0?u.getPort():(secure?443:80);
        socket=secure?SSLSocketFactory.getDefault().createSocket(u.getHost(),port):new Socket(u.getHost(),port);socket.setSoTimeout(0);in=socket.getInputStream();out=socket.getOutputStream();
        byte[] nonce=new byte[16];random.nextBytes(nonce);String key=Base64.encodeToString(nonce,Base64.NO_WRAP);
        String path=(u.getRawPath()==null||u.getRawPath().isEmpty()?"/":u.getRawPath())+(u.getRawQuery()!=null?"?"+u.getRawQuery():"");
        String req="GET "+path+" HTTP/1.1\r\nHost: "+u.getHost()+":"+port+"\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: "+key+"\r\nUser-Agent: Worldforge-Android/0.1\r\n\r\n";
        out.write(req.getBytes(StandardCharsets.US_ASCII));out.flush();String header=readHeader(in);if(!header.startsWith("HTTP/1.1 101"))throw new IOException("WebSocket upgrade failed: "+header.split("\r\n")[0]);
        running=true;listener.onOpen();while(running)readFrame();
    }
    private static String readHeader(InputStream in)throws IOException{ByteArrayOutputStream b=new ByteArrayOutputStream();int state=0,x;while((x=in.read())>=0){b.write(x);state=(state==0&&x=='\r')?1:(state==1&&x=='\n')?2:(state==2&&x=='\r')?3:(state==3&&x=='\n')?4:0;if(state==4)break;if(b.size()>16384)throw new IOException("Header too large");}return new String(b.toByteArray(), StandardCharsets.US_ASCII);}
    private void readFrame()throws Exception{int a=in.read(),b=in.read();if(a<0||b<0)throw new EOFException();int opcode=a&15;long len=b&127;if(len==126)len=((long)in.read()<<8)|in.read();else if(len==127){len=0;for(int i=0;i<8;i++)len=(len<<8)|in.read();}if(len>1_000_000)throw new IOException("Frame too large");byte[] data=readFully(in,(int)len);if(opcode==8){running=false;return;}if(opcode==9){sendControl((byte)0x8A,data);return;}if(opcode==1){try{listener.onMessage(new JSONObject(new String(data,StandardCharsets.UTF_8)));}catch(Exception ignored){}}}
    private static byte[] readFully(InputStream in,int len)throws IOException{byte[] b=new byte[len];int off=0;while(off<len){int n=in.read(b,off,len-off);if(n<0)throw new EOFException();off+=n;}return b;}
    public synchronized void send(JSONObject obj){if(!running||out==null)return;try{sendText(obj.toString());}catch(Exception e){listener.onError(e);}}
    private void sendText(String text)throws IOException{byte[] data=text.getBytes(StandardCharsets.UTF_8),mask=new byte[4];random.nextBytes(mask);ByteArrayOutputStream f=new ByteArrayOutputStream();f.write(0x81);int n=data.length;if(n<126)f.write(0x80|n);else if(n<65536){f.write(0x80|126);f.write((n>>8)&255);f.write(n&255);}else throw new IOException("Message too large");f.write(mask);for(int i=0;i<n;i++)f.write(data[i]^mask[i%4]);out.write(f.toByteArray());out.flush();}
    private void sendControl(byte first,byte[] data)throws IOException{byte[] mask=new byte[4];random.nextBytes(mask);out.write(first);out.write(0x80|data.length);out.write(mask);for(int i=0;i<data.length;i++)out.write(data[i]^mask[i%4]);out.flush();}
    public void close(){running=false;closeQuiet();}
    private void closeQuiet(){try{if(socket!=null)socket.close();}catch(Exception ignored){}}
}
