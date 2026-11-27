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
import java.util.Locale;
import java.util.Queue;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.logging.Level;
import org.bukkit.command.CommandSender;

/**
 * Высоконадёжный отказоустойчивый WebSocket-клиент моста между Minecraft (Paper/Leaf) и Discord-ботом.
 * Включает многоуровневую матрицу обхода блокировок РКН (Cloudflare WSS 443, Alt HTTPS/HTTP порты, direct VPS, Bot-Hosting, Docker).
 */
public class BridgeClient implements WebSocket.Listener {
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
    private final Queue<String> sendQueue = new ConcurrentLinkedQueue<>();
    private final AtomicBoolean isSending = new AtomicBoolean(false);
    private volatile long lastHeartbeatTime = System.currentTimeMillis();
    private volatile String lastWorkingUrl = null;
    private volatile String lastDisconnectReason = "";
    private volatile long lastOfflineLogTime = 0L;

    public BridgeClient(VanillaBridge plugin) {
        this.plugin = plugin;
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(6L))
                .build();
    }

    /**
     * Адаптивный таймаут подключения:
     * Для локальных адресов loopback/Docker — 2 сек (мгновенный отсев отсутствующих контейнеров).
     * Для внешних доменов и Cloudflare — 6 сек (достаточно для TLS рукопожатия без задержки цикла).
     */
    public static Duration getTimeoutForUrl(String url) {
        if (url == null) return Duration.ofSeconds(5L);
        String low = url.toLowerCase(Locale.ROOT);
        if (low.contains("127.0.0.1") || low.contains("localhost")
                || low.contains("172.17.") || low.contains("172.18.")
                || low.contains("172.19.") || low.contains("172.20.")
                || low.contains("10.0.") || low.contains("host.docker.internal")) {
            return Duration.ofSeconds(2L);
        }
        return Duration.ofSeconds(6L);
    }

    /**
     * Формирует полный приоритетный список маршрутов (способов) подключения с обходом блокировок РКН.
     * Приоритет оптимизирован под размещение бота и сервера на одном хостинге с автоматическим фоллбэком.
     */
    public List<String> buildCandidates() {
        ArrayList<String> raw = new ArrayList<>();

        // 1. Наивысший приоритет: последний подтвержденный рабочий маршрут
        if (this.lastWorkingUrl != null && !this.lastWorkingUrl.trim().isEmpty()) {
            raw.add(this.lastWorkingUrl.trim());
        }

        // 2. Явно сконфигурированный адрес в config.yml
        String configured = this.plugin.getConfig().getString("bridge.ws-url", "").trim();
        if (!configured.isEmpty()) {
            raw.add(configured);
        }

        // 3. Пользовательский список резервных адресов из config.yml (bridge.fallback-urls)
        List<String> fallbacks = this.plugin.getConfig().getStringList("bridge.fallback-urls");
        if (fallbacks != null) {
            for (String fb : fallbacks) {
                if (fb != null && !fb.trim().isEmpty()) {
                    raw.add(fb.trim());
                }
            }
        }

        // 4. Локальные петли и шлюзы Docker (наивысшая надежность при работе на одном VPS/хосте)
        raw.add("ws://127.0.0.1:25007/ws");
        raw.add("ws://127.0.0.1:25549/ws");
        raw.add("ws://172.17.0.1:25007/ws");
        raw.add("ws://172.17.0.1:25549/ws");
        raw.add("ws://172.18.0.1:25007/ws");
        raw.add("ws://172.18.0.1:25549/ws");
        raw.add("ws://host.docker.internal:25007/ws");
        raw.add("ws://host.docker.internal:25549/ws");
        raw.add("ws://10.0.0.1:25007/ws");
        raw.add("ws://10.0.0.1:25549/ws");

        // 5. Прямые выделенные порты публичного домена сервера (213.171.18.142)
        raw.add("ws://play.vanillaland.fun:25007/ws");
        raw.add("ws://play.vanillaland.fun:25549/ws");
        raw.add("ws://213.171.18.142:25007/ws");
        raw.add("ws://213.171.18.142:25549/ws");

        // 6. Главные защищенные WSS маршруты Cloudflare (Порт 443 — стандартный HTTPS, обход РКН при внешнем хосте)
        raw.add("wss://bridge.vanillaland.fun/ws");
        raw.add("wss://play.vanillaland.fun/ws");
        raw.add("wss://vanillaland.fun/ws");
        raw.add("wss://vanillaland.store/ws");

        // 7. Альтернативные HTTPS/WSS порты Cloudflare
        raw.add("wss://bridge.vanillaland.fun:8443/ws");
        raw.add("wss://bridge.vanillaland.fun:2053/ws");
        raw.add("wss://bridge.vanillaland.fun:2083/ws");
        raw.add("wss://bridge.vanillaland.fun:2087/ws");
        raw.add("wss://bridge.vanillaland.fun:2096/ws");
        raw.add("wss://play.vanillaland.fun:8443/ws");

        // 8. Альтернативные HTTP/WS порты Cloudflare
        raw.add("ws://bridge.vanillaland.fun:80/ws");
        raw.add("ws://bridge.vanillaland.fun:8080/ws");
        raw.add("ws://bridge.vanillaland.fun:8880/ws");
        raw.add("ws://bridge.vanillaland.fun:2052/ws");
        raw.add("ws://bridge.vanillaland.fun:2082/ws");
        raw.add("ws://bridge.vanillaland.fun:2086/ws");
        raw.add("ws://bridge.vanillaland.fun:2095/ws");
        raw.add("ws://play.vanillaland.fun:80/ws");
        raw.add("ws://play.vanillaland.fun:8080/ws");

        // 9. Дополнительные порты домена bridge
        raw.add("ws://bridge.vanillaland.fun:25007/ws");
        raw.add("ws://bridge.vanillaland.fun:25549/ws");

        // Дедупликация с сохранением строгого порядка приоритетов
        ArrayList<String> unique = new ArrayList<>();
        for (String url : raw) {
            if (url == null || url.trim().isEmpty()) continue;
            String clean = url.trim();
            if (!unique.contains(clean)) {
                unique.add(clean);
            }
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
            } catch (Exception ignored) {}
            this.reconnectTask = null;
        }
        this.isConnecting.set(true);

        List<String> candidates = this.buildCandidates();
        if (candidates.isEmpty()) {
            candidates.add("ws://127.0.0.1:25007/ws");
        }

        int idx = Math.abs(this.candidateIndex.get()) % candidates.size();
        String targetWsUrl = candidates.get(idx);
        String token = this.plugin.getConfig().getString("bridge.token", "").trim();
        if (token.isEmpty() || "CHANGE_ME_SET_YOUR_BRIDGE_SECRET".equals(token)) {
            this.isConnecting.set(false);
            this.plugin.getLogger().warning("[Мост] Не задан bridge.token в config.yml — подключение к мосту отменено.");
            return;
        }
        String fullUrl = targetWsUrl;

        boolean debug = this.plugin.getConfig().getBoolean("bridge.debug", false);
        if (debug) {
            this.plugin.getLogger().info("[Мост Debug] Попытка подключения (" + (idx + 1) + "/" + candidates.size() + "): " + targetWsUrl);
        }

        UniversalScheduler.runAsync(this.plugin, () -> {
            try {
                Duration timeout = getTimeoutForUrl(targetWsUrl);
                URI uri = URI.create(fullUrl);
                String host = uri.getHost();
                if (host == null || host.isEmpty()) {
                    host = "vanillaland.fun";
                }

                this.httpClient.newWebSocketBuilder()
                        .connectTimeout(timeout)
                        .header("Authorization", "Bearer " + token)
                        .header("User-Agent", "Mozilla/5.0 VanillaBridge/1.4 (Minecraft Server; Anti-RKN)")
                        .header("Origin", "https://vanillaland.fun")
                        .buildAsync(URI.create(fullUrl), this)
                        .whenComplete((ws, throwable) -> {
                            this.isConnecting.set(false);
                            if (throwable != null) {
                                if (debug) {
                                    this.plugin.getLogger().warning("[Мост Debug] Способ (" + (idx + 1) + "/" + candidates.size() + ") недоступен (" + targetWsUrl + "): " + throwable.getMessage());
                                } else {
                                    long now = System.currentTimeMillis();
                                    if (now - this.lastOfflineLogTime > 30000L) {
                                        this.lastOfflineLogTime = now;
                                        this.plugin.getLogger().warning("[Мост] Соединение с Discord ботом отсутствует. Выполняется автоматический фоновый подбор рабочего маршрута...");
                                    }
                                }
                                this.candidateIndex.incrementAndGet();
                                this.handleDisconnect("Connect failed: " + throwable.getMessage(), true);
                            } else {
                                this.webSocket = ws;
                                this.isConnected.set(true);
                                this.reconnectAttempts.set(0);
                                this.candidateIndex.set(idx);
                                this.lastWorkingUrl = targetWsUrl;
                                this.lastHeartbeatTime = System.currentTimeMillis();
                                this.startHeartbeat();
                                this.plugin.getLogger().info("\u2705 [Мост] Успешное подключение к Discord боту через способ #" + (idx + 1) + " (" + targetWsUrl + ")!");
                                this.checkAndAutoUpdateConfig(targetWsUrl);
                                this.plugin.onBridgeConnected();
                                this.drainQueue();
                            }
                        });
            } catch (Exception e) {
                this.isConnecting.set(false);
                long now = System.currentTimeMillis();
                if (debug || now - this.lastOfflineLogTime > 30000L) {
                    this.lastOfflineLogTime = now;
                    this.plugin.getLogger().warning("[Мост] Ошибка инициализации сокета для " + targetWsUrl + ": " + e.getMessage());
                }
                this.candidateIndex.incrementAndGet();
                this.handleDisconnect("Init exception: " + e.getMessage(), true);
            }
        });
    }

    private void checkAndAutoUpdateConfig(String workingUrl) {
        String configuredUrl = this.plugin.getConfig().getString("bridge.ws-url", "").trim();
        if (!workingUrl.equalsIgnoreCase(configuredUrl)) {
            this.plugin.getLogger().info("\u26a1 [Автоподмена конфига] Обнаружен рабочий адрес моста: " + workingUrl);
            this.plugin.getLogger().info("\u26a1 [Автоподмена конфига] Автоматически сохраняем приоритетный bridge.ws-url в config.yml...");
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
            } catch (Exception ignored) {}
            this.reconnectTask = null;
        }
        if (this.webSocket != null) {
            try {
                this.webSocket.sendClose(1000, "Plugin disabled");
            } catch (Exception ignored) {}
            try {
                this.webSocket.abort();
            } catch (Exception ignored) {}
            this.webSocket = null;
        }
        this.messageBuffer.setLength(0);
        this.sendQueue.clear();
        this.isSending.set(false);
    }

    public boolean isConnected() {
        return this.isConnected.get();
    }

    public String getLastWorkingUrl() {
        return this.lastWorkingUrl != null ? this.lastWorkingUrl : "";
    }

    public String getLastDisconnectReason() {
        return this.lastDisconnectReason != null ? this.lastDisconnectReason : "";
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
                        this.plugin.getLogger().warning("Ошибка передачи пакета через WebSocket: " + throwable.getMessage());
                        this.handleDisconnect("Send error: " + throwable.getMessage(), false);
                    } else {
                        this.drainQueue();
                    }
                });
            } catch (Exception e) {
                this.isSending.set(false);
                this.plugin.getLogger().warning("Исключение при отправке пакета: " + e.getMessage());
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
            if (now - this.lastHeartbeatTime > 75000L) {
                this.plugin.getLogger().warning("Обрыв связи с Discord ботом: нет ответа более 75 сек. Принудительный реконнект...");
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
            } catch (Exception ignored) {}
            this.heartbeatTask = null;
        }
    }

    public synchronized void handleDisconnect(String reason, boolean fastFailover) {
        boolean wasOpen = this.isConnected.get();
        if (wasOpen && reason != null && !reason.isEmpty()) {
            this.lastDisconnectReason = reason;
        } else if ((this.lastDisconnectReason == null || this.lastDisconnectReason.isEmpty()) && reason != null && !reason.isEmpty()) {
            this.lastDisconnectReason = reason;
        }
        if (!wasOpen && !this.isConnecting.get() && (this.reconnectTask != null && !this.reconnectTask.isCancelled())) {
            return;
        }
        this.isConnected.set(false);
        this.isConnecting.set(false);
        this.stopHeartbeat();
        if (this.webSocket != null) {
            try {
                this.webSocket.abort();
            } catch (Exception ignored) {}
            this.webSocket = null;
        }
        this.sendQueue.clear();
        this.isSending.set(false);
        this.scheduleReconnect(fastFailover);
    }

    @Override
    public void onOpen(WebSocket webSocket) {
        WebSocket.Listener.super.onOpen(webSocket);
        this.webSocket = webSocket;
        this.isConnected.set(true);
        webSocket.request(1L);
        try {
            String sId = this.plugin.getConfig().getString("server-id", "main");
            String route = this.lastWorkingUrl != null ? this.lastWorkingUrl : this.plugin.getConfig().getString("bridge.ws-url", "");
            String discReason = this.lastDisconnectReason != null ? this.lastDisconnectReason : "";
            String hs = String.format(
                    Locale.US,
                    "{\"type\":\"handshake\",\"server_id\":\"%s\",\"ws_url\":\"%s\",\"last_disconnect_reason\":\"%s\"}",
                    VanillaBridge.escapeJson(sId),
                    VanillaBridge.escapeJson(route),
                    VanillaBridge.escapeJson(discReason)
            );
            this.send(hs);
            this.plugin.sendServerStats();
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
                } catch (Exception e) {
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
        this.plugin.getLogger().info("Соединение с Discord ботом закрыто (" + statusCode + ": " + reason + ").");
        this.candidateIndex.incrementAndGet();
        this.handleDisconnect("onClose: " + statusCode, true);
        return WebSocket.Listener.super.onClose(webSocket, statusCode, reason);
    }

    @Override
    public void onError(WebSocket webSocket, Throwable error) {
        this.plugin.getLogger().warning("Ошибка сокета моста: " + (error != null ? error.getMessage() : "unknown"));
        this.candidateIndex.incrementAndGet();
        this.handleDisconnect("onError: " + (error != null ? error.getMessage() : "unknown"), true);
        WebSocket.Listener.super.onError(webSocket, error);
    }

    private synchronized void scheduleReconnect(boolean fastFailover) {
        if (!this.plugin.isEnabled()) {
            return;
        }
        if (this.isConnected.get()) {
            return;
        }
        if (this.reconnectTask != null && !this.reconnectTask.isCancelled()) {
            return;
        }
        int delaySec;
        if (fastFailover) {
            // Быстрый перебор следующего кандидата (1 сек) без спама в консоль
            delaySec = 1;
        } else {
            int attempt = this.reconnectAttempts.getAndIncrement();
            delaySec = Math.min(15, Math.max(3, 3 + attempt * 2));
        }
        boolean debug = this.plugin.getConfig().getBoolean("bridge.debug", false);
        if (debug) {
            this.plugin.getLogger().info("[Мост Debug] Повторное подключение запланировано через " + delaySec + " сек...");
        }
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
        }, (long) delaySec * 20L);
    }

    /**
     * Запуск расширенной сетевой диагностики моста (DNS, TCP, Health, Обходы РКН).
     */
    public void runDiagnostic(CommandSender sender) {
        UniversalScheduler.runAsync(this.plugin, () -> {
            sender.sendMessage("§e[VanillaBridge] §fЗапуск полной сетевой диагностики маршрутов моста (обход РКН)...§r");
            List<String> candidates = this.buildCandidates();
            sender.sendMessage("§7Проверка всех доступных способов подключения (всего маршрутов: §e" + candidates.size() + "§7):§r");

            int num = 1;
            int workingCount = 0;
            for (String wsUrl : candidates) {
                try {
                    URI uri = URI.create(wsUrl);
                    String host = uri.getHost();
                    int port = uri.getPort() > 0 ? uri.getPort() : (wsUrl.startsWith("wss") ? 443 : 80);

                    String categoryLabel;
                    if (wsUrl.startsWith("wss://")) {
                        categoryLabel = "§b[Cloudflare WSS (Обход РКН)]§r";
                    } else if (wsUrl.contains("81.30.105.141")) {
                        categoryLabel = "§e[Прямой VPS]§r";
                    } else if (wsUrl.contains("bot-hosting") || wsUrl.contains("65.21.202.154")) {
                        categoryLabel = "§d[Bot-Hosting Cloud]§r";
                    } else if (wsUrl.contains("127.0.0.1") || wsUrl.contains("172.") || wsUrl.contains("docker")) {
                        categoryLabel = "§7[Локальный/Docker]§r";
                    } else {
                        categoryLabel = "§f[Прямой домен]§r";
                    }

                    sender.sendMessage("§6[" + num + "] " + categoryLabel + " §f" + wsUrl);

                    // 1. DNS резолв
                    try {
                        InetAddress addr = InetAddress.getByName(host);
                        sender.sendMessage("§7     DNS: §a✓ §f" + host + " -> " + addr.getHostAddress());
                    } catch (Exception e) {
                        sender.sendMessage("§7     DNS: §c✗ Ошибка резолва (блокировка РКН): §7" + e.getMessage());
                        num++;
                        continue;
                    }

                    // 2. TCP проверка порта
                    boolean tcpOk = false;
                    try (Socket socket = new Socket()) {
                        int tcpTimeout = (wsUrl.contains("127.0.0.1") || wsUrl.contains("172.")) ? 1500 : 3500;
                        socket.connect(new InetSocketAddress(host, port), tcpTimeout);
                        sender.sendMessage("§7     TCP " + port + ": §a✓ ОТКРЫТ И ДОСТУПЕН!");
                        tcpOk = true;
                        workingCount++;
                    } catch (SocketTimeoutException e) {
                        sender.sendMessage("§7     TCP " + port + ": §c✗ ТАЙМАУТ (порт или IP блокируется фаерволом/РКН)");
                    } catch (Exception e) {
                        sender.sendMessage("§7     TCP " + port + ": §c✗ Ошибка TCP: §7" + e.getMessage());
                    }

                    // 3. HTTP /health эндпоинт
                    if (tcpOk) {
                        String scheme = wsUrl.startsWith("wss") ? "https://" : "http://";
                        String portPart = (port == 80 || port == 443) ? "" : ":" + port;
                        String healthUrl = scheme + host + portPart + "/health";
                        try {
                            HttpRequest req = HttpRequest.newBuilder()
                                    .uri(URI.create(healthUrl))
                                    .timeout(Duration.ofSeconds(3L))
                                    .header("User-Agent", "VanillaBridge/1.4")
                                    .GET()
                                    .build();
                            HttpResponse<String> resp = this.httpClient.send(req, HttpResponse.BodyHandlers.ofString());
                            if (resp.statusCode() == 200) {
                                sender.sendMessage("§7     HTTP /health: §a✓ 200 OK -> " + resp.body());
                            } else {
                                sender.sendMessage("§7     HTTP /health: §e⚠ Код ответа: " + resp.statusCode());
                            }
                        } catch (Exception e) {
                            sender.sendMessage("§7     HTTP /health: §8(веб-эндпоинт /health не ответил: " + e.getMessage() + ")");
                        }
                    }
                } catch (Exception e) {
                    sender.sendMessage("§c  Ошибка проверки маршрута " + wsUrl + ": " + e.getMessage());
                }
                num++;
            }

            sender.sendMessage("§7--------------------------------------------------");
            sender.sendMessage("§eРезультат диагностики: доступно рабочих способов §a" + workingCount + " §eиз §a" + candidates.size());
            sender.sendMessage("§7Текущий статус WebSocket моста: " + (this.isConnected.get() ? "§aПОДКЛЮЧЕН §2(✔)" : "§cНЕ ПОДКЛЮЧЕН §4(✘)"));
            if (this.isConnected.get()) {
                int curIdx = Math.abs(this.candidateIndex.get()) % candidates.size();
                sender.sendMessage("§aАктивный рабочий маршрут: §f" + candidates.get(curIdx));
            }
        });
    }
}
