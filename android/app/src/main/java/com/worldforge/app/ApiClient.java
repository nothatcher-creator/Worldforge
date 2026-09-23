package com.worldforge.app;

import org.json.JSONObject;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class ApiClient {
    public interface Callback { void done(JSONObject value, Exception error); }
    private final ExecutorService io = Executors.newFixedThreadPool(4);
    private volatile String baseUrl;
    private volatile String token;

    public ApiClient(String baseUrl, String token) { setBaseUrl(baseUrl); this.token = token; }
    public void setBaseUrl(String value) {
        String v = value == null ? "" : value.trim();
        while (v.endsWith("/")) v = v.substring(0, v.length()-1);
        this.baseUrl = v;
    }
    public String getBaseUrl() { return baseUrl; }
    public void setToken(String token) { this.token = token; }
    public String getToken() { return token; }

    public void request(String path, String method, JSONObject body, Callback callback) {
        io.execute(() -> {
            JSONObject result = null; Exception failure = null;
            try { result = requestSync(path, method, body); } catch (Exception e) { failure = e; }
            callback.done(result, failure);
        });
    }

    public JSONObject requestSync(String path, String method, JSONObject body) throws Exception {
        URL url = new URL(baseUrl + path);
        HttpURLConnection c = (HttpURLConnection) url.openConnection();
        c.setConnectTimeout(9000); c.setReadTimeout(15000); c.setRequestMethod(method);
        c.setRequestProperty("Accept", "application/json");
        c.setRequestProperty("User-Agent", "Worldforge-Android/0.4");
        if (token != null && !token.isEmpty()) c.setRequestProperty("Authorization", "Bearer " + token);
        if (body != null) {
            c.setDoOutput(true); c.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            try (OutputStream out = c.getOutputStream()) { out.write(body.toString().getBytes(StandardCharsets.UTF_8)); }
        }
        int code = c.getResponseCode();
        InputStream in = code >= 200 && code < 300 ? c.getInputStream() : c.getErrorStream();
        String text = readAll(in);
        JSONObject obj = text.isEmpty() ? new JSONObject() : new JSONObject(text);
        if (code < 200 || code >= 300) throw new IOException("HTTP " + code + ": " + obj.optString("error", text));
        return obj;
    }

    private static String readAll(InputStream in) throws IOException {
        if (in == null) return "";
        ByteArrayOutputStream b = new ByteArrayOutputStream(); byte[] buf = new byte[4096]; int n;
        while ((n = in.read(buf)) >= 0) b.write(buf,0,n);
        return new String(b.toByteArray(), StandardCharsets.UTF_8);
    }
}
