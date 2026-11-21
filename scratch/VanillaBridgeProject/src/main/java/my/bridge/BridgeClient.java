/*
 * Decompiled with CFR 0.152.
 * 
 * Could not load the following classes:
 *  org.bukkit.Bukkit
 *  org.bukkit.command.CommandSender
 *  org.bukkit.plugin.Plugin
 *  org.bukkit.scheduler.BukkitTask
 */
package my.bridge;

import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.SocketTimeoutException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.WebSocket;
import java.nio.ByteBuffer;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Queue;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.logging.Level;
import my.bridge.VanillaBridge;
import org.bukkit.Bukkit;
import org.bukkit.command.CommandSender;
import org.bukkit.plugin.Plugin;
import org.bukkit.scheduler.BukkitTask;

public class BridgeClient
implements WebSocket.Listener {
    private final VanillaBridge plugin;
    private final HttpClient httpClient;
    private WebSocket webSocket;
    private final AtomicBoolean isConnecting = new AtomicBoolean(false);
    private final AtomicBoolean isConnected = new AtomicBoolean(false);
    private final AtomicInteger reconnectAttempts = new AtomicInteger(0);
    private final AtomicInteger candidateIndex = new AtomicInteger(0);
    private final StringBuilder messageBuffer = new StringBuilder();
    private UniversalScheduler.TaskHandle reconnectTask = null;
    private UniversalScheduler.TaskHandle heartbeatTask = null;
    private final Queue<String> sendQueue = new ConcurrentLinkedQueue<String>();
    private final AtomicBoolean isSending = new AtomicBoolean(false);
    private volatile long lastHeartbeatTime = System.currentTimeMillis();

    public BridgeClient(VanillaBridge plugin) {
        this.plugin = plugin;
        this.httpClient = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(15L)).build();
    }

    public List<String> buildCandidates() {
        ArrayList<String> raw = new ArrayList<String>();
        String configured = this.plugin.getConfig().getString("bridge.ws-url", "").trim();
        if (!configured.isEmpty()) {
            raw.add(configured);
        }
        raw.add("ws://127.0.0.1:25007/ws");
        raw.add("ws://172.17.0.1:25007/ws");
        raw.add("ws://172.18.0.1:25007/ws");
        raw.add("ws://81.30.105.141:25007/ws");
        raw.add("ws://127.0.0.1:25549/ws");
        raw.add("ws://172.17.0.1:25549/ws");
        raw.add("ws://81.30.105.141:25549/ws");
        raw.add("ws://play.vanillaland.fun:25007/ws");
        raw.add("wss://bridge.vanillaland.fun/ws");
        ArrayList<String> unique = new ArrayList<String>();
        for (String url : raw) {
            if (url == null || url.trim().isEmpty() || unique.contains(url.trim())) continue;
            unique.add(url.trim());
        }
        return unique;
    }

    public synchronized void connect() {
        if (this.isConnected.get() || this.isConnecting.get()) {
            return;
        }
        if (this.reconnectTask != null) {
            try {
                this.reconnectTask.cancel();
            }
            catch (Exception exception) {
                // empty catch block
            }
            this.reconnectTask = null;
        }
        this.isConnecting.set(true);
        List<String> candidates = this.buildCandidates();
        if (candidates.isEmpty()) {
            candidates.add("wss://bridge.vanillaland.fun/ws");
        }
        int idx = Math.abs(this.candidateIndex.get()) % candidates.size();
        String targetWsUrl = candidates.get(idx);
        String token = this.plugin.getConfig().getString("bridge.token", "vanillaland_secret_2026");
        String fullUrl = targetWsUrl + (targetWsUrl.contains("?") ? "&" : "?") + "token=" + token;
        this.plugin.getLogger().info("[\u041c\u043e\u0441\u0442] \u041f\u043e\u043f\u044b\u0442\u043a\u0430 \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u044f (" + (idx + 1) + "/" + candidates.size() + "): " + targetWsUrl);
        UniversalScheduler.runAsync(this.plugin, () -> {
            try {
                this.httpClient.newWebSocketBuilder().connectTimeout(Duration.ofSeconds(15L)).header("User-Agent", "Mozilla/5.0 VanillaBridge/1.0 (Minecraft Server)").header("Origin", "https://vanillaland.fun").buildAsync(URI.create(fullUrl), this).whenComplete((ws, throwable) -> {
                    this.isConnecting.set(false);
                    if (throwable != null) {
                        this.plugin.getLogger().warning("[\u041c\u043e\u0441\u0442] \u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0438\u0442\u044c\u0441\u044f \u043a " + targetWsUrl + ": " + throwable.getMessage());
                        this.candidateIndex.incrementAndGet();
                        this.handleDisconnect("Connect failed: " + throwable.getMessage(), true);
                    } else {
                        this.webSocket = ws;
                        this.isConnected.set(true);
                        this.reconnectAttempts.set(0);
                        this.candidateIndex.set(idx);
                        this.lastHeartbeatTime = System.currentTimeMillis();
                        this.startHeartbeat();
                        this.plugin.getLogger().info("\u2705 [\u041c\u043e\u0441\u0442] \u0423\u0441\u043f\u0435\u0448\u043d\u043e\u0435 \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u0435 \u043a Discord \u0431\u043e\u0442\u0443 (" + targetWsUrl + ")!");
                        this.checkAndAutoUpdateConfig(targetWsUrl);
                        this.plugin.onBridgeConnected();
                        this.drainQueue();
                    }
                });
            }
            catch (Exception e) {
                this.isConnecting.set(false);
                this.plugin.getLogger().warning("[\u041c\u043e\u0441\u0442] \u041e\u0448\u0438\u0431\u043a\u0430 \u0438\u043d\u0438\u0446\u0438\u0430\u043b\u0438\u0437\u0430\u0446\u0438\u0438 \u0441\u043e\u043a\u0435\u0442\u0430 \u0434\u043b\u044f " + targetWsUrl + ": " + e.getMessage());
                this.candidateIndex.incrementAndGet();
                this.handleDisconnect("Init exception: " + e.getMessage(), true);
            }
        });
    }

    private void checkAndAutoUpdateConfig(String workingUrl) {
        String configuredUrl = this.plugin.getConfig().getString("bridge.ws-url", "").trim();
        if (!workingUrl.equalsIgnoreCase(configuredUrl)) {
            this.plugin.getLogger().info("\u26a1 [\u0410\u0432\u0442\u043e\u043f\u043e\u0434\u043c\u0435\u043d\u0430 \u043a\u043e\u043d\u0444\u0438\u0433\u0430] \u041e\u0431\u043d\u0430\u0440\u0443\u0436\u0435\u043d \u0440\u0430\u0431\u043e\u0447\u0438\u0439 \u0430\u0434\u0440\u0435\u0441 \u043c\u043e\u0441\u0442\u0430: " + workingUrl);
            this.plugin.getLogger().info("\u26a1 [\u0410\u0432\u0442\u043e\u043f\u043e\u0434\u043c\u0435\u043d\u0430 \u043a\u043e\u043d\u0444\u0438\u0433\u0430] \u0410\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0438 \u043f\u0435\u0440\u0435\u0437\u0430\u043f\u0438\u0441\u044b\u0432\u0430\u0435\u043c bridge.ws-url \u0432 config.yml...");
            this.plugin.updateWsUrlInConfig(workingUrl);
        }
    }

    public synchronized void disconnect() {
        this.isConnected.set(false);
        this.isConnecting.set(false);
        this.stopHeartbeat();
        if (this.reconnectTask != null) {
            try {
                this.reconnectTask.cancel();
            }
            catch (Exception exception) {
                // empty catch block
            }
            this.reconnectTask = null;
        }
        if (this.webSocket != null) {
            try {
                this.webSocket.abort();
            }
            catch (Exception exception) {
                // empty catch block
            }
            try {
                this.webSocket.sendClose(1000, "Plugin disabled");
            }
            catch (Exception exception) {
                // empty catch block
            }
            this.webSocket = null;
        }
        this.sendQueue.clear();
        this.isSending.set(false);
    }

    public boolean isConnected() {
        return this.isConnected.get();
    }

    public void send(String jsonPayload) {
        if (!this.isConnected.get() || this.webSocket == null) {
            return;
        }
        this.sendQueue.offer(jsonPayload);
        this.drainQueue();
    }

    private void drainQueue() {
        if (this.webSocket == null || !this.isConnected.get()) {
            this.sendQueue.clear();
            this.isSending.set(false);
            return;
        }
        if (this.isSending.compareAndSet(false, true)) {
            String next = this.sendQueue.poll();
            if (next == null) {
                this.isSending.set(false);
                return;
            }
            try {
                this.webSocket.sendText(next, true).whenComplete((ws, throwable) -> {
                    this.isSending.set(false);
                    if (throwable != null) {
                        this.plugin.getLogger().warning("\u041e\u0448\u0438\u0431\u043a\u0430 \u043f\u0435\u0440\u0435\u0434\u0430\u0447\u0438 \u043f\u0430\u043a\u0435\u0442\u0430 \u0447\u0435\u0440\u0435\u0437 WebSocket: " + throwable.getMessage());
                        this.handleDisconnect("Send error: " + throwable.getMessage(), false);
                    } else {
                        this.drainQueue();
                    }
                });
            }
            catch (Exception e) {
                this.isSending.set(false);
                this.plugin.getLogger().warning("\u0418\u0441\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u0435 \u043f\u0440\u0438 \u043e\u0442\u043f\u0440\u0430\u0432\u043a\u0435 \u043f\u0430\u043a\u0435\u0442\u0430: " + e.getMessage());
                this.handleDisconnect("sendText exception: " + e.getMessage(), false);
            }
        }
    }

    private void startHeartbeat() {
        this.stopHeartbeat();
        this.lastHeartbeatTime = System.currentTimeMillis();
        this.heartbeatTask = UniversalScheduler.runAsyncTimer(this.plugin, () -> {
            if (!this.isConnected.get() || this.webSocket == null) {
                return;
            }
            long now = System.currentTimeMillis();
            if (now - this.lastHeartbeatTime > 45000L) {
                this.plugin.getLogger().warning("\u041e\u0431\u0440\u044b\u0432 \u0441\u0432\u044f\u0437\u0438 \u0441 Discord \u0431\u043e\u0442\u043e\u043c: \u043d\u0435\u0442 \u043e\u0442\u0432\u0435\u0442\u0430 \u0431\u043e\u043b\u0435\u0435 45 \u0441\u0435\u043a. \u041f\u0440\u0438\u043d\u0443\u0434\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u0439 \u0440\u0435\u043a\u043e\u043d\u043d\u0435\u043a\u0442...");
                this.candidateIndex.incrementAndGet();
                this.handleDisconnect("Heartbeat timeout", true);
                return;
            }
            this.send("{\"type\":\"ping\",\"time\":" + now + "}");
        }, 300L, 300L);
    }

    private void stopHeartbeat() {
        if (this.heartbeatTask != null) {
            try {
                this.heartbeatTask.cancel();
            }
            catch (Exception exception) {
                // empty catch block
            }
            this.heartbeatTask = null;
        }
    }

    public synchronized void handleDisconnect(String reason, boolean fastFailover) {
        if (!(this.isConnected.get() || this.isConnecting.get() || this.reconnectTask == null || this.reconnectTask.isCancelled())) {
            return;
        }
        this.isConnected.set(false);
        this.isConnecting.set(false);
        this.stopHeartbeat();
        if (this.webSocket != null) {
            try {
                this.webSocket.abort();
            }
            catch (Exception exception) {
                // empty catch block
            }
            this.webSocket = null;
        }
        this.sendQueue.clear();
        this.isSending.set(false);
        this.scheduleReconnect(fastFailover);
    }

    @Override
    public void onOpen(WebSocket webSocket) {
        WebSocket.Listener.super.onOpen(webSocket);
        webSocket.request(1L);
        try {
            String sId = this.plugin.getConfig().getString("server-id", "main");
            boolean twoFa = this.plugin.isTwoFactorEnabled();
            String hs = String.format(java.util.Locale.US, "{\"type\":\"handshake\",\"server_id\":\"%s\",\"2fa_enabled\":%b}", sId, twoFa);
            this.send(hs);
        } catch (Exception ignored) {}
    }

    @Override
    public CompletionStage<?> onText(WebSocket webSocket, CharSequence data, boolean last) {
        this.lastHeartbeatTime = System.currentTimeMillis();
        this.messageBuffer.append(data);
        if (last) {
            String fullMessage = this.messageBuffer.toString();
            this.messageBuffer.setLength(0);
            UniversalScheduler.runGlobal(this.plugin, () -> {
                try {
                    this.plugin.handleIncomingMessage(fullMessage);
                }
                catch (Exception e) {
                    this.plugin.getLogger().log(Level.WARNING, "Ошибка обработки сообщения от Discord: " + e.getMessage(), e);
                }
            });
        }
        webSocket.request(1L);
        return WebSocket.Listener.super.onText(webSocket, data, last);
    }

    @Override
    public CompletionStage<?> onPing(WebSocket webSocket, ByteBuffer message) {
        this.lastHeartbeatTime = System.currentTimeMillis();
        webSocket.request(1L);
        return WebSocket.Listener.super.onPing(webSocket, message);
    }

    @Override
    public CompletionStage<?> onPong(WebSocket webSocket, ByteBuffer message) {
        this.lastHeartbeatTime = System.currentTimeMillis();
        webSocket.request(1L);
        return WebSocket.Listener.super.onPong(webSocket, message);
    }

    @Override
    public CompletionStage<?> onClose(WebSocket webSocket, int statusCode, String reason) {
        this.plugin.getLogger().info("\u0421\u043e\u0435\u0434\u0438\u043d\u0435\u043d\u0438\u0435 \u0441 Discord \u0431\u043e\u0442\u043e\u043c \u0437\u0430\u043a\u0440\u044b\u0442\u043e (" + statusCode + ": " + reason + ").");
        this.candidateIndex.incrementAndGet();
        this.handleDisconnect("onClose: " + statusCode, true);
        return WebSocket.Listener.super.onClose(webSocket, statusCode, reason);
    }

    @Override
    public void onError(WebSocket webSocket, Throwable error) {
        this.plugin.getLogger().warning("\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u043e\u043a\u0435\u0442\u0430 \u043c\u043e\u0441\u0442\u0430: " + (error != null ? error.getMessage() : "unknown"));
        this.candidateIndex.incrementAndGet();
        this.handleDisconnect("onError: " + (error != null ? error.getMessage() : "unknown"), true);
        WebSocket.Listener.super.onError(webSocket, error);
    }

    private synchronized void scheduleReconnect(boolean fastFailover) {
        int delaySec;
        if (!this.plugin.isEnabled()) {
            return;
        }
        if (this.isConnected.get()) {
            return;
        }
        if (this.reconnectTask != null && !this.reconnectTask.isCancelled()) {
            return;
        }
        if (fastFailover) {
            delaySec = 2;
        } else {
            int attempt = this.reconnectAttempts.getAndIncrement();
            delaySec = Math.min(10, Math.max(3, 3 + attempt * 2));
        }
        this.plugin.getLogger().info("[\u041c\u043e\u0441\u0442] \u041f\u043e\u0432\u0442\u043e\u0440\u043d\u043e\u0435 \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u0435 \u0437\u0430\u043f\u043b\u0430\u043d\u0438\u0440\u043e\u0432\u0430\u043d\u043e \u0447\u0435\u0440\u0435\u0437 " + delaySec + " \u0441\u0435\u043a...");
        this.reconnectTask = UniversalScheduler.runAsyncLater(this.plugin, () -> {
            this.reconnectTask = null;
            if (!this.plugin.isEnabled()) {
                return;
            }
            if (this.isConnected.get()) {
                return;
            }
            this.isConnecting.set(false);
            this.connect();
        }, (long)delaySec * 20L);
    }

    public void runDiagnostic(CommandSender sender) {
        UniversalScheduler.runAsync(this.plugin, () -> {
            sender.sendMessage("\u00a7e[VanillaBridge] \u00a7f\u0417\u0430\u043f\u0443\u0441\u043a \u043f\u043e\u043b\u043d\u043e\u0439 \u0441\u0435\u0442\u0435\u0432\u043e\u0439 \u0434\u0438\u0430\u0433\u043d\u043e\u0441\u0442\u0438\u043a\u0438 \u043c\u043e\u0441\u0442\u0430...");
            List<String> candidates = this.buildCandidates();
            sender.sendMessage("\u00a77\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0432\u0441\u0435\u0445 \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u044b\u0445 \u043c\u0430\u0440\u0448\u0440\u0443\u0442\u043e\u0432 \u043a \u0431\u043e\u0442\u0443 (\u0432\u0441\u0435\u0433\u043e \u043a\u0430\u043d\u0434\u0438\u0434\u0430\u0442\u043e\u0432: " + candidates.size() + "):");
            int num = 1;
            for (String wsUrl : candidates) {
                block18: {
                    try {
                        URI uri = URI.create(wsUrl);
                        String host = uri.getHost();
                        int port = uri.getPort() > 0 ? uri.getPort() : (wsUrl.startsWith("wss") ? 443 : 80);
                        sender.sendMessage("\u00a76[" + num + "] \u00a7f" + wsUrl);
                        try {
                            InetAddress addr = InetAddress.getByName(host);
                            sender.sendMessage("\u00a77     DNS: \u00a7a\u2713 \u00a7f" + host + " -> " + addr.getHostAddress());
                        }
                        catch (Exception e) {
                            sender.sendMessage("\u00a77     DNS: \u00a7c\u2717 \u041e\u0448\u0438\u0431\u043a\u0430: " + e.getMessage());
                            ++num;
                            continue;
                        }
                        try (Socket socket = new Socket();){
                            socket.connect(new InetSocketAddress(host, port), 3000);
                            sender.sendMessage("\u00a77     TCP " + port + ": \u00a7a\u2713 \u041e\u0422\u041a\u0420\u042b\u0422 \u0418 \u0414\u041e\u0421\u0422\u0423\u041f\u0415\u041d!");
                        }
                        catch (SocketTimeoutException e) {
                            sender.sendMessage("\u00a77     TCP " + port + ": \u00a7c\u2717 \u0422\u0410\u0419\u041c\u0410\u0423\u0422 (\u043f\u043e\u0440\u0442 \u0437\u0430\u0431\u043b\u043e\u043a\u0438\u0440\u043e\u0432\u0430\u043d \u0444\u0430\u0435\u0440\u0432\u043e\u043b\u043e\u043c/\u0445\u043e\u0441\u0442\u0438\u043d\u0433\u043e\u043c)");
                            ++num;
                            continue;
                        }
                        catch (Exception e) {
                            sender.sendMessage("\u00a77     TCP " + port + ": \u00a7c\u2717 \u041e\u0448\u0438\u0431\u043a\u0430 TCP: " + e.getMessage());
                            ++num;
                            continue;
                        }
                        String scheme = wsUrl.startsWith("wss") ? "https://" : "http://";
                        String portPart = port == 80 || port == 443 ? "" : ":" + port;
                        String healthUrl = scheme + host + portPart + "/health";
                        try {
                            HttpRequest req = HttpRequest.newBuilder().uri(URI.create(healthUrl)).timeout(Duration.ofSeconds(4L)).header("User-Agent", "VanillaBridge/1.0").GET().build();
                            HttpResponse<String> resp = this.httpClient.send(req, HttpResponse.BodyHandlers.ofString());
                            if (resp.statusCode() == 200) {
                                sender.sendMessage("\u00a77     HTTP /health: \u00a7a\u2713 200 OK -> " + resp.body());
                                break block18;
                            }
                            sender.sendMessage("\u00a77     HTTP /health: \u00a7e\u26a0 \u041a\u043e\u0434: " + resp.statusCode());
                        }
                        catch (Exception e) {
                            sender.sendMessage("\u00a77     HTTP /health: \u00a7e\u26a0 \u041e\u0448\u0438\u0431\u043a\u0430: " + e.getMessage());
                        }
                    }
                    catch (Exception e) {
                        sender.sendMessage("\u00a7c  \u041e\u0448\u0438\u0431\u043a\u0430 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0438 " + wsUrl + ": " + e.getMessage());
                    }
                }
                ++num;
            }
            sender.sendMessage("\u00a77--------------------------------------------------");
            sender.sendMessage("\u00a77\u0422\u0435\u043a\u0443\u0449\u0438\u0439 \u0441\u0442\u0430\u0442\u0443\u0441 WebSocket \u043c\u043e\u0441\u0442\u0430: " + (this.isConnected.get() ? "\u00a7a\u041f\u041e\u0414\u041a\u041b\u042e\u0427\u0415\u041d" : "\u00a7c\u041d\u0415 \u041f\u041e\u0414\u041a\u041b\u042e\u0427\u0415\u041d"));
            if (this.isConnected.get()) {
                int curIdx = Math.abs(this.candidateIndex.get()) % candidates.size();
                sender.sendMessage("\u00a7a\u0410\u043a\u0442\u0438\u0432\u043d\u044b\u0439 \u0440\u0430\u0431\u043e\u0447\u0438\u0439 \u043c\u0430\u0440\u0448\u0440\u0443\u0442: \u00a7f" + candidates.get(curIdx));
            }
        });
    }
}

