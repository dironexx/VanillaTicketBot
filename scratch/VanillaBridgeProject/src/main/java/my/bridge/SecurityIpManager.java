/*
 * Decompiled with CFR 0.152.
 * 
 * Could not load the following classes:
 *  net.kyori.adventure.text.Component
 *  net.kyori.adventure.text.minimessage.MiniMessage
 *  net.kyori.adventure.title.Title
 *  net.kyori.adventure.title.Title$Times
 *  org.bukkit.Bukkit
 *  org.bukkit.Location
 *  org.bukkit.Sound
 *  org.bukkit.entity.Player
 *  org.bukkit.plugin.Plugin
 *  org.bukkit.scheduler.BukkitTask
 */
package my.bridge;

import java.io.File;
import java.io.FileReader;
import java.io.FileWriter;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.logging.Level;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import my.bridge.VanillaBridge;
import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.minimessage.MiniMessage;
import net.kyori.adventure.title.Title;
import org.bukkit.Bukkit;
import org.bukkit.Location;
import org.bukkit.Sound;
import org.bukkit.entity.Player;
import org.bukkit.plugin.Plugin;
import org.bukkit.scheduler.BukkitTask;

public class SecurityIpManager {
    private final VanillaBridge plugin;
    private final Map<UUID, PendingAuthSession> pendingSessions = new ConcurrentHashMap<UUID, PendingAuthSession>();
    private final Map<String, Long> localIpSessions = new ConcurrentHashMap<String, Long>();
    private final Map<String, Long> localIpDurations = new ConcurrentHashMap<String, Long>();
    private final File storageFile;
    private final File durationsFile;
    private static final long DEFAULT_SESSION_DURATION_MS = 172800000L;
    private volatile long defaultTrustDurationMs = 172800000L;
    private static final Pattern SESSION_PARSE_PATTERN = Pattern.compile("\"([^\"]+)\"\\s*:\\s*([0-9]+)");

    public SecurityIpManager(VanillaBridge plugin) {
        this.plugin = plugin;
        this.storageFile = new File(plugin.getDataFolder(), "ip_sessions.json");
        this.durationsFile = new File(plugin.getDataFolder(), "ip_session_durations.json");
        this.loadSessions();
        this.loadDurations();
    }

    public boolean isIpTrusted(String playerName, String ip) {
        if (playerName == null || ip == null) {
            return false;
        }
        String key = playerName.trim().toLowerCase(Locale.ROOT) + ":" + ip.trim();
        Long expiresAt = this.localIpSessions.get(key);
        if (expiresAt == null) {
            return false;
        }
        if (System.currentTimeMillis() > expiresAt) {
            this.localIpSessions.remove(key);
            this.saveSessionsAsync();
            return false;
        }
        long duration = this.localIpDurations.getOrDefault(key, this.defaultTrustDurationMs);
        if (duration <= 0L) {
            this.localIpSessions.remove(key);
            this.localIpDurations.remove(key);
            this.saveSessionsAsync();
            return false;
        }
        this.localIpSessions.put(key, System.currentTimeMillis() + duration);
        this.saveSessionsAsync();
        return true;
    }

    public void trustIp(String playerName, String ip, long durationMs) {
        if (playerName == null || ip == null) {
            return;
        }
        String key = playerName.trim().toLowerCase(Locale.ROOT) + ":" + ip.trim();
        if (durationMs <= 0L) {
            this.localIpSessions.remove(key);
            this.localIpDurations.remove(key);
            this.saveSessionsAsync();
            return;
        }
        this.localIpSessions.put(key, System.currentTimeMillis() + durationMs);
        this.localIpDurations.put(key, durationMs);
        this.saveSessionsAsync();
    }

    public void setDefaultTrustHours(int hours) {
        this.defaultTrustDurationMs = hours > 0 ? (long)hours * 3600000L : 0L;
    }

    public int getDefaultTrustHours() {
        return (int)(this.defaultTrustDurationMs / 3600000L);
    }

    public int getTrustHoursFor(String playerName, String ip) {
        if (playerName == null || ip == null) {
            return this.getDefaultTrustHours();
        }
        String key = playerName.trim().toLowerCase(Locale.ROOT) + ":" + ip.trim();
        long duration = this.localIpDurations.getOrDefault(key, this.defaultTrustDurationMs);
        return (int)(duration / 3600000L);
    }

    public void revokeIp(String playerName, String ip) {
        if (playerName == null || ip == null) {
            return;
        }
        String key = playerName.trim().toLowerCase(Locale.ROOT) + ":" + ip.trim();
        this.localIpSessions.remove(key);
        this.saveSessionsAsync();
    }

    public void clearPlayerSessions(String playerName) {
        if (playerName == null) {
            return;
        }
        String prefix = playerName.trim().toLowerCase(Locale.ROOT) + ":";
        this.localIpSessions.keySet().removeIf(k -> k.startsWith(prefix));
        this.localIpDurations.keySet().removeIf(k -> k.startsWith(prefix));
        this.saveSessionsAsync();
    }

    public boolean isPending2FA(UUID uuid) {
        return this.pendingSessions.containsKey(uuid);
    }

    public PendingAuthSession getSession(UUID uuid) {
        return this.pendingSessions.get(uuid);
    }

    public boolean isSessionMatching(UUID uuid, String incomingSessionId) {
        if (uuid == null || incomingSessionId == null || incomingSessionId.isEmpty()) {
            return true;
        }
        PendingAuthSession session = this.pendingSessions.get(uuid);
        if (session == null) {
            return false;
        }
        String currentId = session.getSessionId();
        return currentId == null || currentId.isEmpty() || currentId.equals(incomingSessionId);
    }

    public void start2FA(Player player, String code, String ip, int timeoutSeconds) {
        this.start2FA(player, code, ip, timeoutSeconds, false);
    }

    public void start2FA(Player player, String code, String ip, int timeoutSeconds, boolean dmClosed) {
        this.start2FA(player, code, ip, timeoutSeconds, dmClosed, this.getDefaultTrustHours(), "");
    }

    public void start2FA(Player player, String code, String ip, int timeoutSeconds, boolean dmClosed, int trustHours) {
        this.start2FA(player, code, ip, timeoutSeconds, dmClosed, trustHours, "");
    }

    public void start2FA(Player player, String code, String ip, int timeoutSeconds, boolean dmClosed, int trustHours, String sessionId) {
        if (player == null || !player.isOnline()) {
            return;
        }
        if (!Bukkit.isPrimaryThread()) {
            Bukkit.getScheduler().runTask((Plugin)this.plugin, () -> this.start2FA(player, code, ip, timeoutSeconds, dmClosed, trustHours, sessionId));
            return;
        }
        UUID uuid = player.getUniqueId();
        this.cancel(uuid);
        int safeTimeout = timeoutSeconds > 0 ? timeoutSeconds : 180;
        long expiresAt = System.currentTimeMillis() + (long)safeTimeout * 1000L;
        Location freezeLoc = player.getLocation().clone();
        PendingAuthSession session = new PendingAuthSession(uuid, player.getName(), ip, code, expiresAt, freezeLoc, trustHours, sessionId);
        try {
            player.playSound(player.getLocation(), Sound.BLOCK_CHEST_LOCKED, 1.0f, 0.8f);
            player.playSound(player.getLocation(), Sound.BLOCK_NOTE_BLOCK_BASS, 1.0f, 0.5f);
        }
        catch (Exception exception) {
            // empty catch block
        }
        String subtitleText = dmClosed ? "<red>\u041e\u0442\u043a\u0440\u043e\u0439\u0442\u0435 \u041b\u0421 \u0431\u043e\u0442\u0430 \u0432 Discord!</red>" : "<yellow>\u041a\u043e\u0434 \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d \u0432 Discord! <white>/code [\u043a\u043e\u0434 \u0438\u0437 \u041b\u0421]</white></yellow>";
        Title title = Title.title((Component)MiniMessage.miniMessage().deserialize("<gradient:#FF416C:#FF4B2B><bold>\ud83d\udd12 \u041f\u041e\u0414\u0422\u0412\u0415\u0420\u0416\u0414\u0415\u041d\u0418\u0415 \u0412\u0425\u041e\u0414\u0410</bold></gradient>"), (Component)MiniMessage.miniMessage().deserialize(subtitleText), (Title.Times)Title.Times.times((Duration)Duration.ofMillis(300L), (Duration)Duration.ofMillis(5000L), (Duration)Duration.ofMillis(500L)));
        player.showTitle(title);
        String dmWarning = dmClosed ? "  <red><bold>\u26a0\ufe0f \u0412\u041d\u0418\u041c\u0410\u041d\u0418\u0415: \u0411\u043e\u0442 \u043d\u0435 \u0441\u043c\u043e\u0433 \u043e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c \u0432\u0430\u043c \u043a\u043e\u0434 \u0432 Discord!</bold></red>\n  <red>\u0423 \u0432\u0430\u0441 \u0437\u0430\u043a\u0440\u044b\u0442\u044b \u043b\u0438\u0447\u043d\u044b\u0435 \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u044f \u043e\u0442 \u0443\u0447\u0430\u0441\u0442\u043d\u0438\u043a\u043e\u0432 \u0441\u0435\u0440\u0432\u0435\u0440\u0430 \u0432 Discord.</red>\n  <yellow>\u0420\u0430\u0437\u0440\u0435\u0448\u0438\u0442\u0435 \u0432\u0445\u043e\u0434\u044f\u0449\u0438\u0435 \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u044f \u0432 \u043d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0430\u0445 \u043a\u043e\u043d\u0444\u0438\u0434\u0435\u043d\u0446\u0438\u0430\u043b\u044c\u043d\u043e\u0441\u0442\u0438 Discord \u0438 \u043f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u0435 \u0432\u0445\u043e\u0434.</yellow>\n\n" : "";
        String trustLabel = trustHours > 0 ? trustHours + "\u0447" : "\u0441\u0442\u0440\u043e\u0433\u0438\u0439 \u0440\u0435\u0436\u0438\u043c";
        player.sendMessage(MiniMessage.miniMessage().deserialize(("\n<gradient:#FF416C:#FF4B2B><bold>\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501 \u2726 \u0411\u0415\u0417\u041e\u041f\u0410\u0421\u041d\u041e\u0421\u0422\u042c \u2726 \u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501</bold></gradient>\n  <red><bold>\u0412\u043d\u0438\u043c\u0430\u043d\u0438\u0435! \u0414\u043b\u044f \u0432\u0445\u043e\u0434\u0430 \u0442\u0440\u0435\u0431\u0443\u0435\u0442\u0441\u044f \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0438\u0435 \u0430\u043a\u043a\u0430\u0443\u043d\u0442\u0430.</bold></red>\n  <gray>\u041e\u0431\u043d\u0430\u0440\u0443\u0436\u0435\u043d \u043d\u043e\u0432\u044b\u0439 IP \u0430\u0434\u0440\u0435\u0441 \u0438\u043b\u0438 \u0438\u0441\u0442\u0435\u043a\u043b\u0430 \u0434\u043e\u0432\u0435\u0440\u0435\u043d\u043d\u0430\u044f \u0441\u0435\u0441\u0441\u0438\u044f (" + trustLabel + "): <white>" + ip + "</white></gray>\n\n" + dmWarning + "  <yellow>\u2022 \u0421\u043f\u043e\u0441\u043e\u0431 1:</yellow> <white>\u041d\u0430\u0436\u043c\u0438\u0442\u0435 \u0437\u0435\u043b\u0451\u043d\u0443\u044e \u043a\u043d\u043e\u043f\u043a\u0443 \u0432 \u041b\u0421 \u0431\u043e\u0442\u0430 \u0432 Discord</white>\n  <yellow>\u2022 \u0421\u043f\u043e\u0441\u043e\u0431 2:</yellow> <white>\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043a\u043e\u043c\u0430\u043d\u0434\u0443 <yellow><click:suggest_command:'/code '>/code [6 \u0446\u0438\u0444\u0440 \u0438\u0437 Discord]</click></yellow> \u0438\u043b\u0438 \u043d\u0430\u043f\u0438\u0448\u0438\u0442\u0435 6 \u0446\u0438\u0444\u0440 \u0432 \u0447\u0430\u0442</white>\n  <dark_gray>\u0421\u0440\u043e\u043a \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u044f \u043a\u043e\u0434\u0430: " + safeTimeout / 60 + " \u043c\u0438\u043d. \u041f\u0435\u0440\u0435\u0434\u0432\u0438\u0436\u0435\u043d\u0438\u0435 \u0438 \u043a\u043e\u043c\u0430\u043d\u0434\u044b \u043e\u0433\u0440\u0430\u043d\u0438\u0447\u0435\u043d\u044b.</dark_gray>\n<gradient:#FF416C:#FF4B2B><bold>\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501</bold></gradient>\n")));
        session.reminderTask = Bukkit.getScheduler().runTaskTimer((Plugin)this.plugin, () -> {
            Player p = Bukkit.getPlayer((UUID)uuid);
            if (p != null && p.isOnline()) {
                p.sendActionBar(MiniMessage.miniMessage().deserialize(("<gradient:#FF416C:#FF4B2B><bold>\ud83d\udd12 2FA</bold></gradient> <dark_gray>\u2502</dark_gray> " + (dmClosed ? "<red>\u041e\u0442\u043a\u0440\u043e\u0439\u0442\u0435 \u041b\u0421 \u0432 Discord!</red>" : "<gray>\u041a\u043e\u0434 \u0432 Discord \u0438\u043b\u0438: <yellow>/code [\u043a\u043e\u0434]</yellow></gray>"))));
            }
        }, 40L, 40L);
        session.timeoutTask = Bukkit.getScheduler().runTaskLater((Plugin)this.plugin, () -> {
            Player p = Bukkit.getPlayer((UUID)uuid);
            if (p != null && p.isOnline() && this.isPending2FA(uuid)) {
                this.cancel(uuid);
                p.kick(MiniMessage.miniMessage().deserialize("<gradient:#FF416C:#FF4B2B><bold>Vanilla Land</bold></gradient> <dark_gray>\u2502</dark_gray> <red>\u0411\u0435\u0437\u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u044c 2FA</red>\n\n<gray>\u0412\u0440\u0435\u043c\u044f \u043d\u0430 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0438\u0435 \u0432\u0445\u043e\u0434\u0430 \u0438\u0441\u0442\u0435\u043a\u043b\u043e (3 \u043c\u0438\u043d\u0443\u0442\u044b).\n<white>\u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u0442\u0435 \u0432\u0445\u043e\u0434 \u0432 Discord \u043f\u0435\u0440\u0435\u0434 \u0441\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u043c \u0432\u0445\u043e\u0434\u043e\u043c \u043d\u0430 \u0441\u0435\u0440\u0432\u0435\u0440.</white>"));
            }
        }, (long)safeTimeout * 20L);
        this.pendingSessions.put(uuid, session);
    }

    public boolean checkCode(Player player, String enteredCode) {
        String cleanCode;
        if (player == null) {
            return false;
        }
        PendingAuthSession session = this.pendingSessions.get(player.getUniqueId());
        if (session == null) {
            player.sendMessage(MiniMessage.miniMessage().deserialize("<gray>\u0423 \u0432\u0430\u0441 \u043d\u0435\u0442 \u0430\u043a\u0442\u0438\u0432\u043d\u043e\u0433\u043e \u0437\u0430\u043f\u0440\u043e\u0441\u0430 \u043d\u0430 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0438\u0435 2FA.</gray>"));
            return false;
        }
        String string = cleanCode = enteredCode != null ? enteredCode.trim() : "";
        if (cleanCode.equalsIgnoreCase(session.getCode())) {
            this.completeVerification(player, true);
            return true;
        }
        session.incrementAttempts();
        if (session.getAttempts() >= 3) {
            this.cancel(player.getUniqueId());
            player.kick(MiniMessage.miniMessage().deserialize("<gradient:#FF416C:#FF4B2B><bold>Vanilla Land</bold></gradient> <dark_gray>\u2502</dark_gray> <red>\u0411\u0435\u0437\u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u044c 2FA</red>\n\n<red><bold>\u041f\u0440\u0435\u0432\u044b\u0448\u0435\u043d\u043e \u043a\u043e\u043b\u0438\u0447\u0435\u0441\u0442\u0432\u043e \u043f\u043e\u043f\u044b\u0442\u043e\u043a \u0432\u0432\u043e\u0434\u0430 \u043a\u043e\u0434\u0430 (3/3)!</bold></red>\n<gray>\u0412\u0445\u043e\u0434 \u0432 \u0430\u043a\u043a\u0430\u0443\u043d\u0442 \u0437\u0430\u0431\u043b\u043e\u043a\u0438\u0440\u043e\u0432\u0430\u043d \u0432 \u0446\u0435\u043b\u044f\u0445 \u0431\u0435\u0437\u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u0438.\n\u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u0442\u0435 \u0441\u0432\u043e\u044e \u043b\u0438\u0447\u043d\u043e\u0441\u0442\u044c \u0447\u0435\u0440\u0435\u0437 Discord \u043f\u0435\u0440\u0435\u0434 \u0441\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u043c \u0432\u0445\u043e\u0434\u043e\u043c.</gray>"));
            return false;
        }
        int remaining = 3 - session.getAttempts();
        player.sendMessage(MiniMessage.miniMessage().deserialize(("<red>\u274c \u041d\u0435\u0432\u0435\u0440\u043d\u044b\u0439 6-\u0437\u043d\u0430\u0447\u043d\u044b\u0439 \u043a\u043e\u0434 \u0431\u0435\u0437\u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u0438! \u041e\u0441\u0442\u0430\u043b\u043e\u0441\u044c \u043f\u043e\u043f\u044b\u0442\u043e\u043a: <yellow>" + remaining + "/3</yellow></red>")));
        try {
            player.playSound(player.getLocation(), Sound.BLOCK_NOTE_BLOCK_BASS, 1.0f, 0.6f);
        }
        catch (Exception exception) {
            // empty catch block
        }
        return false;
    }

    public void completeVerification(Player player, boolean notifyDiscord) {
        this.completeVerification(player, notifyDiscord, -1);
    }

    public void completeVerification(Player player, boolean notifyDiscord, int trustHours) {
        if (player == null) {
            return;
        }
        if (!Bukkit.isPrimaryThread()) {
            Bukkit.getScheduler().runTask((Plugin)this.plugin, () -> this.completeVerification(player, notifyDiscord, trustHours));
            return;
        }
        UUID uuid = player.getUniqueId();
        PendingAuthSession session = this.pendingSessions.remove(uuid);
        String ip = "127.0.0.1";
        int hours = trustHours >= 0 ? trustHours : (session != null ? session.getTrustHours() : this.getDefaultTrustHours());
        long trustMs = hours > 0 ? (long)hours * 3600000L : 0L;
        if (session != null) {
            session.cancelTasks();
            ip = session.getIp();
            this.trustIp(session.getPlayerName(), ip, trustMs);
        } else {
            if (player.getAddress() != null && player.getAddress().getAddress() != null) {
                ip = player.getAddress().getAddress().getHostAddress();
            }
            this.trustIp(player.getName(), ip, trustMs);
        }
        try {
            player.playSound(player.getLocation(), Sound.ENTITY_PLAYER_LEVELUP, 1.0f, 1.2f);
            player.playSound(player.getLocation(), Sound.UI_TOAST_CHALLENGE_COMPLETE, 0.8f, 1.4f);
        }
        catch (Exception exception) {
            // empty catch block
        }
        if (notifyDiscord && this.plugin.getBridgeClient() != null && this.plugin.getBridgeClient().isConnected()) {
            String payload = String.format(Locale.US, "{\"type\":\"2fa_code_verified\",\"player\":\"%s\",\"ip\":\"%s\"}", VanillaBridge.escapeJson(player.getName()), VanillaBridge.escapeJson(ip));
            this.plugin.getBridgeClient().send(payload);
        }
        String finalIp = ip;
        Bukkit.getScheduler().runTask((Plugin)this.plugin, () -> {
            if (player.isOnline()) {
                Title title = Title.title((Component)MiniMessage.miniMessage().deserialize("<gradient:#00F0FF:#5865F2><bold>VANILLA LAND</bold></gradient>"), (Component)MiniMessage.miniMessage().deserialize("<green>\u2714 \u0412\u0445\u043e\u0434 \u0443\u0441\u043f\u0435\u0448\u043d\u043e \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0451\u043d!</green>"), (Title.Times)Title.Times.times((Duration)Duration.ofMillis(200L), (Duration)Duration.ofMillis(2500L), (Duration)Duration.ofMillis(400L)));
                player.showTitle(title);
                player.sendActionBar(MiniMessage.miniMessage().deserialize("<green>\u2714 \u0414\u0432\u0443\u0445\u0444\u0430\u043a\u0442\u043e\u0440\u043d\u0430\u044f \u0437\u0430\u0449\u0438\u0442\u0430 \u043f\u0440\u043e\u0439\u0434\u0435\u043d\u0430. \u041f\u0440\u0438\u044f\u0442\u043d\u043e\u0439 \u0438\u0433\u0440\u044b!</green>"));
                player.sendMessage(MiniMessage.miniMessage().deserialize(("\n<dark_gray>\u256d\u2500</dark_gray> <gradient:#00F0FF:#5865F2><bold>\u0411\u0435\u0437\u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u044c 2FA \u2022 Vanilla Land</bold></gradient>\n<dark_gray>\u2502</dark_gray> <green>\u2714 <b>\u041b\u0438\u0447\u043d\u043e\u0441\u0442\u044c \u0443\u0441\u043f\u0435\u0448\u043d\u043e \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0430 \u0447\u0435\u0440\u0435\u0437 Discord!</b></green>\n<dark_gray>\u2502</dark_gray> <gray>\u0421\u0435\u0441\u0441\u0438\u044f \u0434\u043b\u044f IP <white>" + finalIp + "</white> \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u0430 \u043d\u0430 <yellow>" + (hours > 0 ? hours + " \u0447\u0430\u0441\u043e\u0432" : "\u043d\u0435 \u0441\u043e\u0445\u0440\u0430\u043d\u044f\u0435\u0442\u0441\u044f (\u0441\u0442\u0440\u043e\u0433\u0438\u0439 \u0440\u0435\u0436\u0438\u043c)") + "</yellow>.</gray>\n<dark_gray>\u2502</dark_gray> <dark_gray>\u0423\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435 \u0441\u0435\u0441\u0441\u0438\u044f\u043c\u0438 \u0438 \u043d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0430\u043c\u0438: <yellow>/security</yellow> \u0432 Discord.</dark_gray>\n<dark_gray>\u2570\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500</dark_gray>\n")));
            }
        });
    }

    public void rejectVerification(Player player, String reason) {
        if (player == null) {
            return;
        }
        if (!Bukkit.isPrimaryThread()) {
            Bukkit.getScheduler().runTask((Plugin)this.plugin, () -> this.rejectVerification(player, reason));
            return;
        }
        this.cancel(player.getUniqueId());
        String safeReason = reason != null && !reason.isEmpty() ? reason : "\u0412\u0445\u043e\u0434 \u043e\u0442\u043a\u043b\u043e\u043d\u0451\u043d \u0432\u043b\u0430\u0434\u0435\u043b\u044c\u0446\u0435\u043c \u0430\u043a\u043a\u0430\u0443\u043d\u0442\u0430 \u0447\u0435\u0440\u0435\u0437 Discord!";
        Bukkit.getScheduler().runTask((Plugin)this.plugin, () -> {
            if (player.isOnline()) {
                player.kick(MiniMessage.miniMessage().deserialize(("<gradient:#FF416C:#FF4B2B><bold>Vanilla Land</bold></gradient> <dark_gray>\u2502</dark_gray> <red>\u0414\u043e\u0441\u0442\u0443\u043f \u0437\u0430\u0431\u043b\u043e\u043a\u0438\u0440\u043e\u0432\u0430\u043d</red>\n\n<red><bold>\u274c " + safeReason + "</bold></red>\n\n<gray>\u0421\u0435\u0441\u0441\u0438\u044f \u043d\u0435 \u0431\u044b\u043b\u0430 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0430 \u0447\u0435\u0440\u0435\u0437 Discord 2FA.\n\u0415\u0441\u043b\u0438 \u044d\u0442\u043e \u0432\u0430\u0448 \u0430\u043a\u043a\u0430\u0443\u043d\u0442 \u2014 \u0441\u043c\u0435\u043d\u0438\u0442\u0435 \u043f\u0430\u0440\u043e\u043b\u044c (/changepassword) \u0438 \u043f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u0435 \u0432\u0445\u043e\u0434.</gray>")));
            }
        });
    }

    public void cancel(UUID uuid) {
        PendingAuthSession session = this.pendingSessions.remove(uuid);
        if (session != null) {
            session.cancelTasks();
        }
    }

    private void loadSessions() {
        if (!this.storageFile.exists()) {
            return;
        }
        try (FileReader reader = new FileReader(this.storageFile, StandardCharsets.UTF_8);){
            int read;
            StringBuilder sb = new StringBuilder();
            char[] buf = new char[1024];
            while ((read = reader.read(buf)) != -1) {
                sb.append(buf, 0, read);
            }
            String content = sb.toString();
            Matcher matcher = SESSION_PARSE_PATTERN.matcher(content);
            long now = System.currentTimeMillis();
            while (matcher.find()) {
                String key = matcher.group(1);
                long expiry = Long.parseLong(matcher.group(2));
                if (expiry <= now) continue;
                this.localIpSessions.put(key, expiry);
            }
            this.plugin.getLogger().info("\u0417\u0430\u0433\u0440\u0443\u0436\u0435\u043d\u043e " + this.localIpSessions.size() + " \u0430\u043a\u0442\u0438\u0432\u043d\u044b\u0445 \u0434\u043e\u0432\u0435\u0440\u0435\u043d\u043d\u044b\u0445 IP-\u0441\u0435\u0441\u0441\u0438\u0439.");
        }
        catch (Exception e) {
            this.plugin.getLogger().log(Level.WARNING, "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u0441\u043e\u0445\u0440\u0430\u043d\u0451\u043d\u043d\u044b\u0435 IP-\u0441\u0435\u0441\u0441\u0438\u0438: " + e.getMessage(), e);
        }
    }

    private void loadDurations() {
        if (!this.durationsFile.exists()) {
            return;
        }
        try (FileReader reader = new FileReader(this.durationsFile, StandardCharsets.UTF_8)) {
            StringBuilder sb = new StringBuilder();
            char[] buf = new char[1024];
            int read;
            while ((read = reader.read(buf)) != -1) {
                sb.append(buf, 0, read);
            }
            Matcher matcher = SESSION_PARSE_PATTERN.matcher(sb.toString());
            while (matcher.find()) {
                String key = matcher.group(1);
                long duration = Long.parseLong(matcher.group(2));
                if (duration > 0L) {
                    this.localIpDurations.put(key, duration);
                }
            }
        }
        catch (Exception e) {
            this.plugin.getLogger().log(Level.WARNING, "Не удалось загрузить IP-дурации: " + e.getMessage(), e);
        }
    }

    private void saveSessionsAsync() {
        Bukkit.getScheduler().runTaskAsynchronously((Plugin)this.plugin, this::saveSessions);
    }

    public synchronized void saveSessions() {
        try {
            if (!this.plugin.getDataFolder().exists()) {
                this.plugin.getDataFolder().mkdirs();
            }
            long now = System.currentTimeMillis();
            StringBuilder json = new StringBuilder("{\n");
            boolean first = true;
            for (Map.Entry<String, Long> entry : this.localIpSessions.entrySet()) {
                if (entry.getValue() <= now) continue;
                if (!first) {
                    json.append(",\n");
                }
                json.append("  \"").append(entry.getKey()).append("\": ").append(entry.getValue());
                first = false;
            }
            json.append("\n}\n");
            try (FileWriter writer = new FileWriter(this.storageFile, StandardCharsets.UTF_8);){
                writer.write(json.toString());
            }
            StringBuilder durationsJson = new StringBuilder("{\n");
            boolean firstDuration = true;
            for (Map.Entry<String, Long> entry : this.localIpDurations.entrySet()) {
                if (!firstDuration) {
                    durationsJson.append(",\n");
                }
                durationsJson.append("  \"").append(entry.getKey()).append("\": ").append(entry.getValue());
                firstDuration = false;
            }
            durationsJson.append("\n}\n");
            try (FileWriter durationsWriter = new FileWriter(this.durationsFile, StandardCharsets.UTF_8);){
                durationsWriter.write(durationsJson.toString());
            }
        }
        catch (Exception e) {
            this.plugin.getLogger().log(Level.WARNING, "\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u0438\u044f IP-\u0441\u0435\u0441\u0441\u0438\u0439: " + e.getMessage(), e);
        }
    }

    public static class PendingAuthSession {
        private final UUID uuid;
        private final String playerName;
        private final String ip;
        private final String code;
        private final long expiresAt;
        private final Location freezeLocation;
        private final int trustHours;
        private final String sessionId;
        private int attempts = 0;
        private BukkitTask reminderTask;
        private BukkitTask timeoutTask;

        public PendingAuthSession(UUID uuid, String playerName, String ip, String code, long expiresAt, Location freezeLocation, int trustHours) {
            this(uuid, playerName, ip, code, expiresAt, freezeLocation, trustHours, "");
        }

        public PendingAuthSession(UUID uuid, String playerName, String ip, String code, long expiresAt, Location freezeLocation, int trustHours, String sessionId) {
            this.uuid = uuid;
            this.playerName = playerName;
            this.ip = ip;
            this.code = code;
            this.expiresAt = expiresAt;
            this.freezeLocation = freezeLocation;
            this.trustHours = trustHours;
            this.sessionId = sessionId != null ? sessionId : "";
        }

        public UUID getUuid() {
            return this.uuid;
        }

        public String getPlayerName() {
            return this.playerName;
        }

        public String getIp() {
            return this.ip;
        }

        public String getCode() {
            return this.code;
        }

        public long getExpiresAt() {
            return this.expiresAt;
        }

        public Location getFreezeLocation() {
            return this.freezeLocation;
        }

        public int getTrustHours() {
            return this.trustHours;
        }

        public String getSessionId() {
            return this.sessionId;
        }

        public int getAttempts() {
            return this.attempts;
        }

        public void incrementAttempts() {
            ++this.attempts;
        }

        public void cancelTasks() {
            if (this.reminderTask != null) {
                this.reminderTask.cancel();
                this.reminderTask = null;
            }
            if (this.timeoutTask != null) {
                this.timeoutTask.cancel();
                this.timeoutTask = null;
            }
        }
    }
}

