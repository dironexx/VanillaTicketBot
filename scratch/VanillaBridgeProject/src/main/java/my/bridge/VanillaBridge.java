/*
 * Decompiled with CFR 0.152.
 * 
 * Could not load the following classes:
 *  com.destroystokyo.paper.profile.PlayerProfile
 *  com.destroystokyo.paper.profile.ProfileProperty
 *  com.google.gson.JsonElement
 *  com.google.gson.JsonObject
 *  com.google.gson.JsonParser
 *  net.kyori.adventure.text.Component
 *  net.kyori.adventure.text.TextComponent
 *  net.kyori.adventure.text.TextComponent$Builder
 *  net.kyori.adventure.text.event.ClickEvent
 *  net.kyori.adventure.text.event.HoverEvent
 *  net.kyori.adventure.text.event.HoverEventSource
 *  net.kyori.adventure.text.format.NamedTextColor
 *  net.kyori.adventure.text.format.TextColor
 *  net.kyori.adventure.text.format.TextDecoration
 *  net.kyori.adventure.text.minimessage.MiniMessage
 *  net.kyori.adventure.text.serializer.legacy.LegacyComponentSerializer
 *  org.bukkit.Bukkit
 *  org.bukkit.Chunk
 *  org.bukkit.Location
 *  org.bukkit.Material
 *  org.bukkit.OfflinePlayer
 *  org.bukkit.Sound
 *  org.bukkit.Statistic
 *  org.bukkit.World
 *  org.bukkit.World$Environment
 *  org.bukkit.block.BlockState
 *  org.bukkit.block.ShulkerBox
 *  org.bukkit.boss.DragonBattle
 *  org.bukkit.boss.DragonBattle$RespawnPhase
 *  org.bukkit.command.Command
 *  org.bukkit.command.CommandExecutor
 *  org.bukkit.command.CommandSender
 *  org.bukkit.configuration.file.FileConfiguration
 *  org.bukkit.configuration.file.YamlConfiguration
 *  org.bukkit.entity.Animals
 *  org.bukkit.entity.Entity
 *  org.bukkit.entity.Item
 *  org.bukkit.entity.Monster
 *  org.bukkit.entity.Player
 *  org.bukkit.event.Listener
 *  org.bukkit.inventory.ItemStack
 *  org.bukkit.inventory.meta.BlockStateMeta
 *  org.bukkit.inventory.meta.ItemMeta
 *  org.bukkit.plugin.Plugin
 *  org.bukkit.plugin.java.JavaPlugin
 *  org.bukkit.potion.PotionEffect
 *  org.bukkit.potion.PotionEffectType
 *  org.bukkit.scheduler.BukkitRunnable
 *  org.bukkit.scheduler.BukkitTask
 */
package my.bridge;

import com.destroystokyo.paper.profile.PlayerProfile;
import com.destroystokyo.paper.profile.ProfileProperty;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.io.File;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.Reader;
import java.lang.reflect.Method;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.OpenOption;
import java.sql.ResultSet;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Collection;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Function;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import my.bridge.AuthMeHook;
import my.bridge.BridgeClient;
import my.bridge.ChatBridgeListener;
import my.bridge.SecurityIpManager;
import my.bridge.SecurityListener;
import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.TextComponent;
import net.kyori.adventure.text.event.ClickEvent;
import net.kyori.adventure.text.event.HoverEvent;
import net.kyori.adventure.text.event.HoverEventSource;
import net.kyori.adventure.text.format.NamedTextColor;
import net.kyori.adventure.text.format.TextColor;
import net.kyori.adventure.text.format.TextDecoration;
import net.kyori.adventure.text.minimessage.MiniMessage;
import net.kyori.adventure.text.serializer.legacy.LegacyComponentSerializer;
import org.bukkit.Bukkit;
import org.bukkit.Chunk;
import org.bukkit.Location;
import org.bukkit.Material;
import org.bukkit.OfflinePlayer;
import org.bukkit.Sound;
import org.bukkit.Statistic;
import org.bukkit.World;
import org.bukkit.block.BlockState;
import org.bukkit.block.ShulkerBox;
import org.bukkit.boss.DragonBattle;
import org.bukkit.command.Command;
import org.bukkit.command.CommandExecutor;
import org.bukkit.command.CommandSender;
import org.bukkit.configuration.file.FileConfiguration;
import org.bukkit.configuration.file.YamlConfiguration;
import org.bukkit.entity.Animals;
import org.bukkit.entity.Entity;
import org.bukkit.entity.Item;
import org.bukkit.entity.Monster;
import org.bukkit.entity.Player;
import org.bukkit.event.Listener;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.meta.BlockStateMeta;
import org.bukkit.inventory.meta.ItemMeta;
import org.bukkit.plugin.Plugin;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.potion.PotionEffect;
import org.bukkit.potion.PotionEffectType;
import org.bukkit.scheduler.BukkitRunnable;
import org.bukkit.scheduler.BukkitTask;

public class VanillaBridge
extends JavaPlugin
implements CommandExecutor {
    private BridgeClient bridgeClient;
    private BukkitTask statsTask;
    private final AtomicBoolean hasSentStartup = new AtomicBoolean(false);
    private long serverStartTime = 0L;
    private boolean twoFactorEnabled = true;
    public boolean isTwoFactorEnabled() { return this.twoFactorEnabled; }
    private static final Pattern URL_PATTERN = Pattern.compile("https?://[a-zA-Z0-9.-]+(?:/[^\\s]*)?", 2);
    private static final Pattern JSON_EXTRACT_PATTERN = Pattern.compile("\"([^\"]+)\"\\s*:\\s*(?:\"((?:\\\\.|[^\"\\\\])*)\"|([a-zA-Z0-9._-]+))");
    private final Map<UUID, String> lastDiscordDmSender = new ConcurrentHashMap<UUID, String>();
    private final Map<UUID, String> lastDiscordDmAuthor = new ConcurrentHashMap<UUID, String>();
    private final Map<String, String> skinCache = new ConcurrentHashMap<String, String>();
    private volatile boolean maintenance = false;
    private volatile String maintenanceReason = "\u0422\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u0438\u0435 \u0440\u0430\u0431\u043e\u0442\u044b \u043d\u0430 \u0441\u0435\u0440\u0432\u0435\u0440\u0435";
    private final Set<String> staffWhitelist = ConcurrentHashMap.newKeySet();
    private BukkitTask maintenanceCountdownTask = null;
    private volatile int countdownRemaining = 0;
    private volatile String countdownMode = "";
    private volatile String countdownReason = "";
    private volatile String cachedTopJson = null;
    private volatile long lastTopCacheTime = 0L;
    private SecurityIpManager securityIpManager;
    private AuthMeHook authMeHook;

    public static int parseDurationSeconds(String input, int defaultSec) {
        if (input == null || input.trim().isEmpty()) {
            return defaultSec;
        }
        String s = input.trim().toLowerCase(Locale.ROOT);
        try {
            if (s.endsWith("m") || s.endsWith("\u043c") || s.endsWith("min")) {
                String num = s.replaceAll("[^0-9]", "");
                return num.isEmpty() ? defaultSec : Integer.parseInt(num) * 60;
            }
            if (s.endsWith("s") || s.endsWith("\u0441") || s.endsWith("sec")) {
                String num = s.replaceAll("[^0-9]", "");
                return num.isEmpty() ? defaultSec : Integer.parseInt(num);
            }
            return Integer.parseInt(s);
        }
        catch (Exception e) {
            return defaultSec;
        }
    }

    public static Component parseFormattedText(String input) {
        if (input == null || input.isEmpty()) {
            return Component.empty();
        }
        String text = input;
        text = text.replaceAll("&?#([A-Fa-f0-9]{6})", "<#$1>");
        text = text.replaceAll("\\{#([A-Fa-f0-9]{6})\\}", "<#$1>");
        text = text.replaceAll("[&\u00a7]0", "<black>").replaceAll("[&\u00a7]1", "<dark_blue>").replaceAll("[&\u00a7]2", "<dark_green>").replaceAll("[&\u00a7]3", "<dark_aqua>").replaceAll("[&\u00a7]4", "<dark_red>").replaceAll("[&\u00a7]5", "<dark_purple>").replaceAll("[&\u00a7]6", "<gold>").replaceAll("[&\u00a7]7", "<gray>").replaceAll("[&\u00a7]8", "<dark_gray>").replaceAll("[&\u00a7]9", "<blue>").replaceAll("[&\u00a7][aA]", "<green>").replaceAll("[&\u00a7][bB]", "<aqua>").replaceAll("[&\u00a7][cC]", "<red>").replaceAll("[&\u00a7][dD]", "<light_purple>").replaceAll("[&\u00a7][eE]", "<yellow>").replaceAll("[&\u00a7][fF]", "<white>").replaceAll("[&\u00a7][lL]", "<bold>").replaceAll("[&\u00a7][oO]", "<italic>").replaceAll("[&\u00a7][nN]", "<underlined>").replaceAll("[&\u00a7][mM]", "<strikethrough>").replaceAll("[&\u00a7][kK]", "<obfuscated>").replaceAll("[&\u00a7][rR]", "<reset>");
        try {
            return MiniMessage.miniMessage().deserialize(text);
        }
        catch (Exception e) {
            try {
                return LegacyComponentSerializer.legacyAmpersand().deserialize(input);
            }
            catch (Exception ignored) {
                return Component.text((String)input);
            }
        }
    }

    public void cachePlayerSkin(String playerName, String skinHash) {
        if (playerName != null && skinHash != null && !skinHash.isEmpty()) {
            this.skinCache.put(playerName.toLowerCase(Locale.ROOT), skinHash);
        }
    }

    public String getCachedPlayerSkin(String playerName) {
        if (playerName == null) {
            return "";
        }
        return this.skinCache.getOrDefault(playerName.toLowerCase(Locale.ROOT), "");
    }

    public static String extractSkinHash(PlayerProfile profile) {
        if (profile == null) {
            return "";
        }
        try {
            String hash;
            String p;
            URL skinUrl;
            if (profile.hasTextures() && (skinUrl = profile.getTextures().getSkin()) != null && (p = skinUrl.getPath()) != null && p.contains("/") && !(hash = p.substring(p.lastIndexOf(47) + 1).trim()).isEmpty()) {
                return hash;
            }
            for (ProfileProperty prop : profile.getProperties()) {
                int start;
                int end;
                byte[] decoded;
                String json;
                int idx;
                String val;
                if (!"textures".equalsIgnoreCase(prop.getName()) || (val = prop.getValue()) == null || val.isEmpty() || (idx = (json = new String(decoded = Base64.getDecoder().decode(val), StandardCharsets.UTF_8)).indexOf("textures.minecraft.net/texture/")) == -1) continue;
                for (end = start = idx + "textures.minecraft.net/texture/".length(); end < json.length() && Character.isLetterOrDigit(json.charAt(end)); ++end) {
                }
                String hash2 = json.substring(start, end).trim();
                if (hash2.isEmpty()) continue;
                return hash2;
            }
        }
        catch (Throwable throwable) {
            // empty catch block
        }
        return "";
    }

    public synchronized void updateWsUrlInConfig(String newUrl) {
        if (newUrl == null || newUrl.trim().isEmpty()) {
            return;
        }
        String trimmed = newUrl.trim();
        this.getConfig().set("bridge.ws-url", (Object)trimmed);
        this.saveConfig();
        try {
            File configFile = new File(this.getDataFolder(), "config.yml");
            if (configFile.exists()) {
                String content = Files.readString(configFile.toPath(), StandardCharsets.UTF_8);
                String updated = content.replaceAll("(?m)^(\\s*ws-url:\\s*)\".*?\"", "$1\"" + trimmed + "\"");
                if (updated.equals(content)) {
                    updated = content.replaceAll("(?m)^(\\s*ws-url:\\s*)[^\"\\r\\n]+", "$1\"" + trimmed + "\"");
                }
                if (!updated.equals(content)) {
                    Files.writeString(configFile.toPath(), (CharSequence)updated, StandardCharsets.UTF_8, new OpenOption[0]);
                    this.getLogger().info("\u041a\u043e\u043d\u0444\u0438\u0433 config.yml \u0443\u0441\u043f\u0435\u0448\u043d\u043e \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d \u043d\u0430 \u0440\u0430\u0431\u043e\u0447\u0438\u0439 \u0430\u0434\u0440\u0435\u0441: " + trimmed);
                }
            }
        }
        catch (Exception e) {
            this.getLogger().warning("\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043f\u0435\u0440\u0435\u0437\u0430\u043f\u0438\u0441\u0430\u0442\u044c ws-url \u0432 config.yml: " + e.getMessage());
        }
    }

    public void migrateConfig() {
        File configFile = new File(this.getDataFolder(), "config.yml");
        // Добавляем ключи, которых нет в старом config.yml, не меняя существующие значения.
        this.saveDefaultConfig();
        this.getConfig().options().copyDefaults(true);
        this.saveConfig();
        this.reloadConfig();
        if (!configFile.exists()) {
            return;
        }
        try {
            String content;
            String original = content = Files.readString(configFile.toPath(), StandardCharsets.UTF_8);
            if (content.contains("fi4.bot-hosting.cloud") || content.contains("65.21.202.154")) {
                content = content.replaceAll("ws://fi4\\.bot-hosting\\.cloud:[0-9]+/ws", "wss://bridge.vanillaland.fun/ws");
                content = content.replaceAll("ws://fi4\\.bot-hosting\\.cloud", "wss://bridge.vanillaland.fun");
                content = content.replaceAll("ws://65\\.21\\.202\\.154:[0-9]+/ws", "wss://bridge.vanillaland.fun/ws");
                content = content.replaceAll("ws://65\\.21\\.202\\.154", "wss://bridge.vanillaland.fun");
            }
            if (content.contains(":25549")) {
                content = content.replaceAll(":25549", ":25007");
            }
            if (!content.equals(original)) {
                Files.writeString(configFile.toPath(), (CharSequence)content, StandardCharsets.UTF_8, new OpenOption[0]);
                this.getLogger().info("\u041a\u043e\u043d\u0444\u0438\u0433\u0443\u0440\u0430\u0446\u0438\u044f config.yml \u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0438 \u0430\u043a\u0442\u0443\u0430\u043b\u0438\u0437\u0438\u0440\u043e\u0432\u0430\u043d\u0430 \u043f\u043e\u0434 \u043d\u043e\u0432\u0443\u044e \u043d\u043e\u0434\u0443 (\u043f\u043e\u0440\u0442 25007).");
            }
        }
        catch (Exception e) {
            this.getLogger().warning("\u041e\u0448\u0438\u0431\u043a\u0430 \u043f\u0440\u0438 \u0442\u0435\u043a\u0441\u0442\u043e\u0432\u043e\u043c \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u0438 config.yml: " + e.getMessage());
        }
        this.reloadConfig();
        FileConfiguration cfg = this.getConfig();
        String currentWsUrl = cfg.getString("bridge.ws-url", "");
        if (currentWsUrl.contains("fi4.bot-hosting.cloud") || currentWsUrl.contains("65.21.202.154") || currentWsUrl.isEmpty()) {
            cfg.set("bridge.ws-url", (Object)"wss://bridge.vanillaland.fun/ws");
            this.saveConfig();
            this.getLogger().info("\u041f\u0430\u0440\u0430\u043c\u0435\u0442\u0440 bridge.ws-url \u0443\u0441\u043f\u0435\u0448\u043d\u043e \u0430\u043a\u0442\u0443\u0430\u043b\u0438\u0437\u0438\u0440\u043e\u0432\u0430\u043d \u0432 \u043a\u043e\u043d\u0444\u0438\u0433\u0443\u0440\u0430\u0446\u0438\u0438 \u0441\u0435\u0440\u0432\u0435\u0440\u0430.");
        } else if (currentWsUrl.contains(":25549")) {
            String updated = currentWsUrl.replace(":25549", ":25007");
            cfg.set("bridge.ws-url", (Object)updated);
            this.saveConfig();
            this.getLogger().info("\u041f\u0430\u0440\u0430\u043c\u0435\u0442\u0440 bridge.ws-url \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d \u043d\u0430 \u043f\u043e\u0440\u0442 25007.");
        }
        try (InputStream defStream = this.getResource("config.yml");){
            if (defStream != null) {
                YamlConfiguration defConfig = YamlConfiguration.loadConfiguration((Reader)new InputStreamReader(defStream, StandardCharsets.UTF_8));
                boolean added = false;
                for (String key : defConfig.getKeys(true)) {
                    if (cfg.contains(key)) continue;
                    cfg.set(key, defConfig.get(key));
                    added = true;
                }
                if (added) {
                    this.saveConfig();
                    this.getLogger().info("\u041d\u043e\u0432\u044b\u0435 \u043f\u0430\u0440\u0430\u043c\u0435\u0442\u0440\u044b \u043a\u043e\u043d\u0444\u0438\u0433\u0443\u0440\u0430\u0446\u0438\u0438 \u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0438 \u0434\u043e\u0431\u0430\u0432\u043b\u0435\u043d\u044b \u0432 config.yml.");
                }
            }
        }
        catch (Exception e) {
            this.getLogger().warning("\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u0438\u043d\u0445\u0440\u043e\u043d\u0438\u0437\u0430\u0446\u0438\u0438 \u0441\u0442\u0440\u0443\u043a\u0442\u0443\u0440\u044b config.yml: " + e.getMessage());
        }
    }

    public void onEnable() {
        this.serverStartTime = System.currentTimeMillis();
        this.migrateConfig();
        this.twoFactorEnabled = this.getConfig().getBoolean("security.two-factor.enabled", true);
        boolean bridgeEnabled = this.getConfig().getBoolean("bridge.enabled", true);
        if (bridgeEnabled) {
            this.bridgeClient = new BridgeClient(this);
            this.bridgeClient.connect();
        } else {
            this.getLogger().info("Подключение к мосту выключено (bridge.enabled: false)");
        }
        this.securityIpManager = new SecurityIpManager(this);
        this.securityIpManager.setDefaultTrustHours(this.getConfig().getInt("security.trust-duration-hours", 48));
        this.getServer().getPluginManager().registerEvents((Listener)new SecurityListener(this, this.securityIpManager), (Plugin)this);
        this.getServer().getPluginManager().registerEvents((Listener)new ChatBridgeListener(this), (Plugin)this);
        this.authMeHook = new AuthMeHook(this);
        this.authMeHook.register();
        if (this.getCommand("bridge") != null) {
            this.getCommand("bridge").setExecutor((CommandExecutor)this);
        }
        if (this.getCommand("code") != null) {
            this.getCommand("code").setExecutor((sender, command, label, args) -> {
                if (!(sender instanceof Player)) {
                    sender.sendMessage("\u00a7c\u0422\u043e\u043b\u044c\u043a\u043e \u0434\u043b\u044f \u0438\u0433\u0440\u043e\u043a\u043e\u0432!");
                    return true;
                }
                Player player = (Player)sender;
                if (this.securityIpManager == null || !this.securityIpManager.isPending2FA(player.getUniqueId())) {
                    player.sendMessage(MiniMessage.miniMessage().deserialize("<gray>\u0423 \u0432\u0430\u0441 \u043d\u0435\u0442 \u0430\u043a\u0442\u0438\u0432\u043d\u043e\u0433\u043e \u0437\u0430\u043f\u0440\u043e\u0441\u0430 \u043d\u0430 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0438\u0435 2FA.</gray>"));
                    return true;
                }
                if (args.length == 0) {
                    player.sendMessage(MiniMessage.miniMessage().deserialize("<dark_gray>\u2502</dark_gray> <yellow>\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u0435: <white>/code [6 \u0446\u0438\u0444\u0440]</white> \u0438\u043b\u0438 <white>/code resend</white></yellow>"));
                    return true;
                }
                String sub = args[0].trim();
                if (sub.equalsIgnoreCase("resend") || sub.equalsIgnoreCase("\u043f\u043e\u0432\u0442\u043e\u0440")) {
                    if (this.bridgeClient != null && this.bridgeClient.isConnected()) {
                        String payload = String.format(Locale.US, "{\"type\":\"2fa_resend_code\",\"player\":\"%s\"}", VanillaBridge.escapeJson(player.getName()));
                        this.bridgeClient.send(payload);
                        player.sendMessage(MiniMessage.miniMessage().deserialize("<dark_gray>\u2502</dark_gray> <gray>\u0417\u0430\u043f\u0440\u043e\u0441 \u043d\u0430 \u043f\u043e\u0432\u0442\u043e\u0440\u043d\u0443\u044e \u043e\u0442\u043f\u0440\u0430\u0432\u043a\u0443 \u043a\u043e\u0434\u0430 \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d \u0432 Discord...</gray>"));
                        try {
                            player.playSound(player.getLocation(), Sound.UI_BUTTON_CLICK, 1.0f, 1.0f);
                        }
                        catch (Exception exception) {}
                    } else {
                        player.sendMessage(MiniMessage.miniMessage().deserialize("<dark_gray>\u2502</dark_gray> <red>\u274c \u0421\u0432\u044f\u0437\u044c \u0441 Discord \u0431\u043e\u0442\u043e\u043c \u0432\u0440\u0435\u043c\u0435\u043d\u043d\u043e \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0430. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u043f\u043e\u0437\u0436\u0435.</red>"));
                    }
                    return true;
                }
                this.securityIpManager.checkCode(player, sub);
                return true;
            });
        }
        if (this.getCommand("link") != null) {
            this.getCommand("link").setExecutor((sender, command, label, args) -> {
                if (!(sender instanceof Player)) {
                    sender.sendMessage("\u00a7c\u0422\u043e\u043b\u044c\u043a\u043e \u0434\u043b\u044f \u0438\u0433\u0440\u043e\u043a\u043e\u0432!");
                    return true;
                }
                Player player = (Player)sender;
                if (args.length == 0) {
                    if (this.bridgeClient != null && this.bridgeClient.isConnected()) {
                        String payload = String.format(Locale.US, "{\"type\":\"mc_request_link_code\",\"player\":\"%s\",\"uuid\":\"%s\"}", VanillaBridge.escapeJson(player.getName()), player.getUniqueId().toString());
                        this.bridgeClient.send(payload);
                    } else {
                        player.sendMessage(MiniMessage.miniMessage().deserialize("<red>\u274c \u0421\u0432\u044f\u0437\u044c \u0441 Discord \u0431\u043e\u0442\u043e\u043c \u0432\u0440\u0435\u043c\u0435\u043d\u043d\u043e \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0430. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u043f\u043e\u0437\u0436\u0435.</red>"));
                    }
                    return true;
                }
                String inputCode = args[0].trim();
                if (!inputCode.matches("^\\d{6}$")) {
                    player.sendMessage(MiniMessage.miniMessage().deserialize("<red>\u041a\u043e\u0434 \u0434\u043e\u043b\u0436\u0435\u043d \u0441\u043e\u0441\u0442\u043e\u044f\u0442\u044c \u0440\u043e\u0432\u043d\u043e \u0438\u0437 6 \u0446\u0438\u0444\u0440!</red>"));
                    return true;
                }
                String ip = "127.0.0.1";
                if (player.getAddress() != null && player.getAddress().getAddress() != null) {
                    ip = player.getAddress().getAddress().getHostAddress();
                }
                if (this.bridgeClient != null && this.bridgeClient.isConnected()) {
                    String payload = String.format(Locale.US, "{\"type\":\"link_attempt\",\"player\":\"%s\",\"uuid\":\"%s\",\"code\":\"%s\",\"ip\":\"%s\"}", VanillaBridge.escapeJson(player.getName()), player.getUniqueId().toString(), inputCode, VanillaBridge.escapeJson(ip));
                    this.bridgeClient.send(payload);
                    player.sendMessage(MiniMessage.miniMessage().deserialize("<gray>\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u043a\u043e\u0434\u0430 \u043f\u0440\u0438\u0432\u044f\u0437\u043a\u0438 \u0441 Discord \u0431\u043e\u0442\u043e\u043c...</gray>"));
                } else {
                    player.sendMessage(MiniMessage.miniMessage().deserialize("<red>\u0421\u0432\u044f\u0437\u044c \u0441 Discord \u0431\u043e\u0442\u043e\u043c \u0432\u0440\u0435\u043c\u0435\u043d\u043d\u043e \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0430. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u043f\u043e\u0437\u0436\u0435.</red>"));
                }
                return true;
            });
        }
        if (this.getCommand("rd") != null) {
            this.getCommand("rd").setExecutor((sender, command, label, args) -> {
                if (!(sender instanceof Player)) {
                    sender.sendMessage("\u00a7c\u041a\u043e\u043c\u0430\u043d\u0434\u0430 \u0442\u043e\u043b\u044c\u043a\u043e \u0434\u043b\u044f \u0438\u0433\u0440\u043e\u043a\u043e\u0432!");
                    return true;
                }
                Player player = (Player)sender;
                if (args.length == 0) {
                    sender.sendMessage(MiniMessage.miniMessage().deserialize("<red>\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u0435: <gradient:#FFA500:#FF7700>/rd [\u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435]</gradient></red>"));
                    return true;
                }
                String authorId = this.lastDiscordDmSender.get(player.getUniqueId());
                String author = this.lastDiscordDmAuthor.get(player.getUniqueId());
                if (authorId == null || authorId.isEmpty()) {
                    sender.sendMessage(MiniMessage.miniMessage().deserialize("<red>\u274c \u0412\u0430\u043c \u0435\u0449\u0451 \u043d\u0438\u043a\u0442\u043e \u043d\u0435 \u043f\u0438\u0441\u0430\u043b \u0438\u0437 Discord!</red>"));
                    return true;
                }
                String replyMsg = String.join((CharSequence)" ", args);
                String payload = String.format(Locale.US, "{\"type\":\"dm_reply\",\"target_id\":\"%s\",\"target_author\":\"%s\",\"player\":\"%s\",\"content\":\"%s\"}", VanillaBridge.escapeJson(authorId), VanillaBridge.escapeJson(author), VanillaBridge.escapeJson(player.getName()), VanillaBridge.escapeJson(replyMsg));
                this.bridgeClient.send(payload);
                String safeAuthor = MiniMessage.miniMessage().escapeTags(author);
                String safeReplyMsg = MiniMessage.miniMessage().escapeTags(replyMsg);
                String replyFormat = "<gradient:#ff7a00:#ffae19>\u2709 Discord \u041b\u0421</gradient> <dark_gray>\u2502</dark_gray> <gray>\u0412\u044b</gray> <gradient:#FFA500:#FF7700>\u2192</gradient> <white><hover:show_text:'&7\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c Discord: &f" + safeAuthor + "'>" + safeAuthor + "</hover></white><dark_gray>:</dark_gray> <white>" + safeReplyMsg + "</white>";
                sender.sendMessage(MiniMessage.miniMessage().deserialize(replyFormat));
                return true;
            });
        }
        if (this.getCommand("maintenance") != null) {
            this.getCommand("maintenance").setExecutor((sender, command, label, args) -> {
                if (!sender.hasPermission("vanillabridge.admin")) {
                    sender.sendMessage(MiniMessage.miniMessage().deserialize("<red>\u274c \u0423 \u0432\u0430\u0441 \u043d\u0435\u0442 \u043f\u0440\u0430\u0432 \u0434\u043b\u044f \u0443\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u044f \u0442\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u0438\u043c\u0438 \u0440\u0430\u0431\u043e\u0442\u0430\u043c\u0438!</red>"));
                    return true;
                }
                if (args.length == 0 || args[0].equalsIgnoreCase("status") || args[0].equalsIgnoreCase("\u0441\u0442\u0430\u0442\u0443\u0441")) {
                    String maintStatus = this.maintenance ? "<red><bold>\u0412\u041a\u041b\u042e\u0427\u0415\u041d\u042b</bold></red>" : "<green><bold>\u0412\u042b\u041a\u041b\u042e\u0427\u0415\u041d\u042b</bold></green>";
                    StringBuilder sb = new StringBuilder("\n<gradient:#FFA500:#FF7700>\u2699 \u0422\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u0438\u0435 \u0440\u0430\u0431\u043e\u0442\u044b:</gradient> " + maintStatus + "\n");
                    if (this.maintenance) {
                        sb.append("<gray>\u041f\u0440\u0438\u0447\u0438\u043d\u0430: <white>").append(MiniMessage.miniMessage().escapeTags(this.maintenanceReason)).append("</white></gray>\n");
                    }
                    if (this.maintenanceCountdownTask != null && this.countdownRemaining > 0) {
                        sb.append(String.format(Locale.US, "<yellow>\u23f1 \u0410\u043a\u0442\u0438\u0432\u043d\u044b\u0439 \u043e\u0431\u0440\u0430\u0442\u043d\u044b\u0439 \u043e\u0442\u0441\u0447\u0451\u0442: <bold>%02d:%02d</bold> (\u0440\u0435\u0436\u0438\u043c: %s)</yellow>\n", this.countdownRemaining / 60, this.countdownRemaining % 60, this.countdownMode));
                        sb.append("<dark_gray>\u0427\u0442\u043e\u0431\u044b \u043e\u0442\u043c\u0435\u043d\u0438\u0442\u044c: /maintenance cancel</dark_gray>\n");
                    } else {
                        sb.append("<dark_gray>\u041a\u043e\u043c\u0430\u043d\u0434\u044b: /maintenance [restart|timer|cancel|extend|on|off]</dark_gray>\n");
                    }
                    sender.sendMessage(MiniMessage.miniMessage().deserialize(sb.toString()));
                    return true;
                }
                String action = args[0].toLowerCase(Locale.ROOT);
                if (action.equals("on") || action.equals("\u0432\u043a\u043b") || action.equals("enable") || action.equals("1")) {
                    String reason = "\u0422\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u043e\u0435 \u043e\u0431\u0441\u043b\u0443\u0436\u0438\u0432\u0430\u043d\u0438\u0435 \u0441\u0435\u0440\u0432\u0435\u0440\u0430";
                    if (args.length > 1) {
                        StringBuilder sb = new StringBuilder();
                        for (int i = 1; i < args.length; ++i) {
                            if (i > 1) {
                                sb.append(" ");
                            }
                            sb.append(args[i]);
                        }
                        reason = sb.toString();
                    }
                    this.maintenance = true;
                    this.maintenanceReason = reason;
                    String safeReason = MiniMessage.miniMessage().escapeTags(reason);
                    Component kickComp = MiniMessage.miniMessage().deserialize(("<gradient:#FFA500:#FF7700><bold>Vanilla Land</bold></gradient> <dark_gray>\u2502</dark_gray> <red>\u0422\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u0438\u0435 \u0440\u0430\u0431\u043e\u0442\u044b</red>\n\n<gray>\u0421\u0435\u0440\u0432\u0435\u0440 \u0432\u0440\u0435\u043c\u0435\u043d\u043d\u043e \u0437\u0430\u043a\u0440\u044b\u0442 \u043d\u0430 \u043e\u0431\u0441\u043b\u0443\u0436\u0438\u0432\u0430\u043d\u0438\u0435:\n<white>" + safeReason + "</white>\n\n<gradient:#00AAFF:#0055FF>\ud83d\uded2 \u0414\u043e\u043d\u0430\u0442:</gradient> <white>vanillaland.store</white>\n<gradient:#FFA500:#FF5500>\ud83c\udf10 \u0421\u0430\u0439\u0442:</gradient> <white>vanillaland.fun</white>\n<gradient:#0088cc:#29b6f6>\u2708 Telegram:</gradient> <white>t.me/vanilandes</white>\n<gradient:#ff7a00:#ffae19>\ud83d\udcac Discord:</gradient> <white>discord.gg/Ba5cMK7F6a</white>"));
                    for (Player p : Bukkit.getOnlinePlayers()) {
                        if (p.isOp() || p.hasPermission("vanillabridge.admin") || this.isStaff(p.getName())) continue;
                        p.kick(kickComp);
                    }
                    if (this.bridgeClient != null && this.bridgeClient.isConnected()) {
                        this.bridgeClient.send(String.format(Locale.US, "{\"type\":\"maintenance\",\"enabled\":true,\"reason\":\"%s\"}", VanillaBridge.escapeJson(reason)));
                    }
                    sender.sendMessage(MiniMessage.miniMessage().deserialize(("<green>\u2714</green> <gradient:#FFA500:#FF7700>\u0420\u0435\u0436\u0438\u043c \u0442\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u0438\u0445 \u0440\u0430\u0431\u043e\u0442 \u0432\u043a\u043b\u044e\u0447\u0435\u043d!</gradient>\n<gray>\u041f\u0440\u0438\u0447\u0438\u043d\u0430: <white>" + safeReason + "</white></gray>\n<dark_gray>\u0418\u0433\u0440\u043e\u043a\u0438 \u0431\u0435\u0437 \u043f\u0440\u0430\u0432 \u0438\u0441\u043a\u043b\u044e\u0447\u0435\u043d\u044b. \u041e\u043f\u043e\u0432\u0435\u0449\u0435\u043d\u0438\u0435 \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u043e \u0432 Discord.</dark_gray>")));
                    return true;
                }
                if (action.equals("off") || action.equals("\u0432\u044b\u043a\u043b") || action.equals("disable") || action.equals("0")) {
                    this.maintenance = false;
                    this.cancelMaintenanceCountdown();
                    if (this.bridgeClient != null && this.bridgeClient.isConnected()) {
                        this.bridgeClient.send("{\"type\":\"maintenance\",\"enabled\":false}");
                        this.bridgeClient.send("{\"type\":\"maintenance_countdown_cancel\"}");
                    }
                    sender.sendMessage(MiniMessage.miniMessage().deserialize("<green>\u2714</green> <gradient:#FFA500:#FF7700>\u0420\u0435\u0436\u0438\u043c \u0442\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u0438\u0445 \u0440\u0430\u0431\u043e\u0442 \u0432\u044b\u043a\u043b\u044e\u0447\u0435\u043d!</gradient>\n<gray>\u0421\u0435\u0440\u0432\u0435\u0440 \u0441\u043d\u043e\u0432\u0430 \u043e\u0442\u043a\u0440\u044b\u0442 \u0434\u043b\u044f \u0432\u0441\u0435\u0445 \u0438\u0433\u0440\u043e\u043a\u043e\u0432. \u041e\u043f\u043e\u0432\u0435\u0449\u0435\u043d\u0438\u0435 \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u043e \u0432 Discord.</gray>"));
                    return true;
                }
                if (action.equals("cancel") || action.equals("\u043e\u0442\u043c\u0435\u043d\u0430") || action.equals("stop") || action.equals("\u0441\u0442\u043e\u043f")) {
                    this.maintenance = false;
                    this.cancelMaintenanceCountdown();
                    if (this.bridgeClient != null && this.bridgeClient.isConnected()) {
                        this.bridgeClient.send("{\"type\":\"maintenance\",\"enabled\":false}");
                        this.bridgeClient.send("{\"type\":\"maintenance_countdown_cancel\"}");
                    }
                    sender.sendMessage(MiniMessage.miniMessage().deserialize("<green>\u2714</green> <gradient:#ff7a00:#ffae19>\u041e\u0431\u0440\u0430\u0442\u043d\u044b\u0439 \u043e\u0442\u0441\u0447\u0451\u0442 \u0438 \u0442\u0435\u0445\u0440\u0430\u0431\u043e\u0442\u044b \u0443\u0441\u043f\u0435\u0448\u043d\u043e \u043e\u0442\u043c\u0435\u043d\u0435\u043d\u044b!</gradient>"));
                    return true;
                }
                if (action.equals("extend") || action.equals("\u043f\u0440\u043e\u0434\u043b\u0438\u0442\u044c") || action.equals("+")) {
                    int sec = 60;
                    if (args.length > 1) {
                        sec = VanillaBridge.parseDurationSeconds(args[1], 60);
                    }
                    this.extendMaintenanceCountdown(sec);
                    if (this.bridgeClient != null && this.bridgeClient.isConnected()) {
                        this.bridgeClient.send(String.format(Locale.US, "{\"type\":\"maintenance_countdown_extend\",\"seconds\":%d}", sec));
                    }
                    sender.sendMessage(MiniMessage.miniMessage().deserialize(("<green>\u2714</green> <gradient:#FFB800:#FFA500>\u0422\u0430\u0439\u043c\u0435\u0440 \u043f\u0440\u043e\u0434\u043b\u0451\u043d \u043d\u0430 +" + (sec >= 60 ? sec / 60 + " \u043c\u0438\u043d." : sec + " \u0441\u0435\u043a.") + "!</gradient>")));
                    return true;
                }
                if (action.equals("restart") || action.equals("\u0440\u0435\u0441\u0442\u0430\u0440\u0442") || action.equals("\u043f\u0435\u0440\u0435\u0437\u0430\u0433\u0440\u0443\u0437\u043a\u0430")) {
                    int sec = 180;
                    String reason = "\u041f\u043b\u0430\u043d\u043e\u0432\u0430\u044f \u043f\u0435\u0440\u0435\u0437\u0430\u0433\u0440\u0443\u0437\u043a\u0430 \u0441\u0435\u0440\u0432\u0435\u0440\u0430";
                    if (args.length > 1) {
                        sec = VanillaBridge.parseDurationSeconds(args[1], 180);
                    }
                    if (args.length > 2) {
                        StringBuilder sb = new StringBuilder();
                        for (int i = 2; i < args.length; ++i) {
                            if (i > 2) {
                                sb.append(" ");
                            }
                            sb.append(args[i]);
                        }
                        reason = sb.toString();
                    }
                    this.startMaintenanceCountdown("restart", sec, reason);
                    if (this.bridgeClient != null && this.bridgeClient.isConnected()) {
                        this.bridgeClient.send(String.format(Locale.US, "{\"type\":\"maintenance_countdown\",\"mode\":\"restart\",\"seconds\":%d,\"reason\":\"%s\"}", sec, VanillaBridge.escapeJson(reason)));
                    }
                    sender.sendMessage(MiniMessage.miniMessage().deserialize(("<green>\u2714</green> <gradient:#ff7a00:#ffae19>\u0417\u0430\u043f\u0443\u0449\u0435\u043d \u0442\u0430\u0439\u043c\u0435\u0440 \u0440\u0435\u0441\u0442\u0430\u0440\u0442\u0430 \u043d\u0430 " + (sec >= 60 ? sec / 60 + " \u043c\u0438\u043d." : sec + " \u0441\u0435\u043a.") + "!</gradient>")));
                    return true;
                }
                if (action.equals("timer") || action.equals("\u0442\u0430\u0439\u043c\u0435\u0440") || action.equals("countdown")) {
                    int sec = 300;
                    String reason = "\u0422\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u043e\u0435 \u043e\u0431\u0441\u043b\u0443\u0436\u0438\u0432\u0430\u043d\u0438\u0435 \u0441\u0435\u0440\u0432\u0435\u0440\u0430";
                    if (args.length > 1) {
                        sec = VanillaBridge.parseDurationSeconds(args[1], 300);
                    }
                    if (args.length > 2) {
                        StringBuilder sb = new StringBuilder();
                        for (int i = 2; i < args.length; ++i) {
                            if (i > 2) {
                                sb.append(" ");
                            }
                            sb.append(args[i]);
                        }
                        reason = sb.toString();
                    }
                    this.startMaintenanceCountdown("lock", sec, reason);
                    if (this.bridgeClient != null && this.bridgeClient.isConnected()) {
                        this.bridgeClient.send(String.format(Locale.US, "{\"type\":\"maintenance_countdown\",\"mode\":\"lock\",\"seconds\":%d,\"reason\":\"%s\"}", sec, VanillaBridge.escapeJson(reason)));
                    }
                    sender.sendMessage(MiniMessage.miniMessage().deserialize(("<green>\u2714</green> <gradient:#FFA500:#FF7700>\u0417\u0430\u043f\u0443\u0449\u0435\u043d \u0442\u0430\u0439\u043c\u0435\u0440 \u0442\u0435\u0445\u0440\u0430\u0431\u043e\u0442 \u043d\u0430 " + (sec >= 60 ? sec / 60 + " \u043c\u0438\u043d." : sec + " \u0441\u0435\u043a.") + "!</gradient>")));
                    return true;
                }
                sender.sendMessage(MiniMessage.miniMessage().deserialize("<red>\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u0435: <yellow>/maintenance [restart|timer|cancel|extend|status|on|off]</yellow></red>"));
                return true;
            });
            this.getCommand("maintenance").setTabCompleter((sender, command, alias, args) -> {
                String a;
                if (args.length == 1) {
                    return List.of("restart", "timer", "cancel", "extend", "status", "on", "off");
                }
                if (args.length == 2 && ((a = args[0].toLowerCase(Locale.ROOT)).equals("restart") || a.equals("timer") || a.equals("extend") || a.equals("\u0440\u0435\u0441\u0442\u0430\u0440\u0442") || a.equals("\u0442\u0430\u0439\u043c\u0435\u0440"))) {
                    return List.of("30s", "1m", "2m", "3m", "5m");
                }
                return Collections.emptyList();
            });
        }
        if (this.getCommand("vbc") != null) {
            this.getCommand("vbc").setExecutor((sender, command, label, args) -> {
                if (!sender.hasPermission("vanillabridge.admin")) {
                    sender.sendMessage(MiniMessage.miniMessage().deserialize("<red>\u274c \u0423 \u0432\u0430\u0441 \u043d\u0435\u0442 \u043f\u0440\u0430\u0432 \u0434\u043b\u044f \u043e\u0442\u043f\u0440\u0430\u0432\u043a\u0438 \u043e\u0431\u044a\u044f\u0432\u043b\u0435\u043d\u0438\u0439!</red>"));
                    return true;
                }
                if (args.length == 0) {
                    sender.sendMessage(MiniMessage.miniMessage().deserialize("<red>\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u0435: <yellow>/vbc [\u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435]</yellow></red>"));
                    return true;
                }
                String text = String.join((CharSequence)" ", args);
                this.broadcastAnnouncement(text, sender.getName(), true);
                return true;
            });
        }
        if (this.getCommand("links") != null) {
            this.getCommand("links").setExecutor((sender, command, label, args) -> {
                sender.sendMessage(this.buildLinksComponent());
                return true;
            });
        }
        if (this.getCommand("discord") != null) {
            this.getCommand("discord").setExecutor((sender, command, label, args) -> {
                sender.sendMessage(this.buildDiscordComponent());
                return true;
            });
        }
        if (this.getCommand("site") != null) {
            this.getCommand("site").setExecutor((sender, command, label, args) -> {
                sender.sendMessage(this.buildSiteComponent());
                return true;
            });
        }
        if (this.getCommand("donate") != null) {
            this.getCommand("donate").setExecutor((sender, command, label, args) -> {
                sender.sendMessage(this.buildDonateComponent());
                return true;
            });
        }
        if (this.getCommand("telegram") != null) {
            this.getCommand("telegram").setExecutor((sender, command, label, args) -> {
                sender.sendMessage(this.buildTelegramComponent());
                return true;
            });
        }
        this.statsTask = Bukkit.getScheduler().runTaskTimerAsynchronously((Plugin)this, this::sendServerStats, 100L, 100L);
        Bukkit.getScheduler().runTaskTimerAsynchronously((Plugin)this, () -> {
            try {
                this.updateTopCache();
            }
            catch (Throwable throwable) {
                // empty catch block
            }
        }, 60L, 3000L);
        this.getLogger().info("VanillaBridge 1.0 \u0443\u0441\u043f\u0435\u0448\u043d\u043e \u0432\u043a\u043b\u044e\u0447\u0435\u043d!");
    }

    public void sendServerStats() {
        if (this.bridgeClient != null && this.bridgeClient.isConnected()) {
            int online = Bukkit.getOnlinePlayers().size();
            int max = Bukkit.getMaxPlayers();
            double tps = Math.min(20.0, Math.max(0.0, Bukkit.getTPS()[0]));
            double mspt = 20.0;
            try {
                mspt = Bukkit.getAverageTickTime();
            }
            catch (Throwable throwable) {
                // empty catch block
            }
            long freeMem = Runtime.getRuntime().freeMemory();
            long totalMem = Runtime.getRuntime().totalMemory();
            long maxMem = Runtime.getRuntime().maxMemory();
            long usedMb = (totalMem - freeMem) / 0x100000L;
            long maxMb = maxMem / 0x100000L;
            StringBuilder playersJson = new StringBuilder("[");
            boolean first = true;
            for (Player p : Bukkit.getOnlinePlayers()) {
                if (!first) {
                    playersJson.append(",");
                }
                playersJson.append("\"").append(VanillaBridge.escapeJson(p.getName())).append("\"");
                first = false;
            }
            playersJson.append("]");
            String payload = String.format(Locale.US, "{\"type\":\"stats\",\"online\":%d,\"max\":%d,\"tps\":%.2f,\"mspt\":%.2f,\"mem_used\":%d,\"mem_max\":%d,\"players\":%s}", online, max, tps, mspt, usedMb, maxMb, playersJson.toString());
            this.bridgeClient.send(payload);
        }
    }

    public void onDisable() {
        if (this.statsTask != null) {
            this.statsTask.cancel();
        }
        if (this.bridgeClient != null) {
            if (this.bridgeClient.isConnected()) {
                this.bridgeClient.send("{\"type\":\"lifecycle\",\"event\":\"stop\"}");
                try {
                    Thread.sleep(150L);
                }
                catch (InterruptedException interruptedException) {
                    // empty catch block
                }
            }
            this.bridgeClient.disconnect();
        }
        this.hasSentStartup.set(false);
        this.getLogger().info("VanillaBridge 1.0 \u0432\u044b\u043a\u043b\u044e\u0447\u0435\u043d.");
    }

    public void onBridgeConnected() {
        if (this.bridgeClient != null && this.bridgeClient.isConnected()) {
            long uptimeMs = System.currentTimeMillis() - this.serverStartTime;
            if (uptimeMs <= 60000L && this.hasSentStartup.compareAndSet(false, true)) {
                this.bridgeClient.send("{\"type\":\"lifecycle\",\"event\":\"start\",\"uptime_ms\":" + uptimeMs + ",\"is_boot\":true}");
            } else {
                this.bridgeClient.send("{\"type\":\"bridge_reconnect\",\"uptime_ms\":" + uptimeMs + "}");
            }
            this.sendServerStats();
        }
    }

    public BridgeClient getBridgeClient() {
        return this.bridgeClient;
    }

    public boolean isMaintenance() {
        return this.maintenance;
    }

    public String getMaintenanceReason() {
        return this.maintenanceReason;
    }

    public boolean isStaff(String playerName) {
        if (playerName == null) {
            return false;
        }
        return this.staffWhitelist.contains(playerName.toLowerCase(Locale.ROOT));
    }

    public void updateStaffWhitelist(Collection<String> names) {
        this.staffWhitelist.clear();
        if (names != null) {
            for (String n : names) {
                if (n == null || n.trim().isEmpty()) continue;
                this.staffWhitelist.add(n.trim().toLowerCase(Locale.ROOT));
            }
        }
    }

    public void cancelMaintenanceCountdown() {
        if (this.maintenanceCountdownTask != null) {
            this.maintenanceCountdownTask.cancel();
            this.maintenanceCountdownTask = null;
        }
        this.countdownRemaining = 0;
        this.countdownMode = "";
        this.countdownReason = "";
        for (Player p : Bukkit.getOnlinePlayers()) {
            p.sendActionBar((Component)Component.empty());
            p.removePotionEffect(PotionEffectType.RESISTANCE);
        }
        Component cancelMsg = MiniMessage.miniMessage().deserialize("\n<gradient:#ff7a00:#ffae19>\u2726 \u2500\u2500 \u2714 \u041e\u0422\u041c\u0415\u041d\u0410 \u0420\u0415\u0421\u0422\u0410\u0420\u0422\u0410 \u2500\u2500 \u2726</gradient>\n  <green><bold>\u041f\u0435\u0440\u0435\u0437\u0430\u0433\u0440\u0443\u0437\u043a\u0430 \u0441\u0435\u0440\u0432\u0435\u0440\u0430 \u043e\u0442\u043c\u0435\u043d\u0435\u043d\u0430 \u0430\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0442\u043e\u0440\u043e\u043c.</bold></green>\n  <gray>\u0421\u0435\u0440\u0432\u0435\u0440 \u043f\u0440\u043e\u0434\u043e\u043b\u0436\u0430\u0435\u0442 \u0440\u0430\u0431\u043e\u0442\u0443 \u0432 \u043e\u0431\u044b\u0447\u043d\u043e\u043c \u0440\u0435\u0436\u0438\u043c\u0435!</gray>\n<gradient:#ff7a00:#ffae19>\u2726 \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 \u2726</gradient>\n");
        for (Player p : Bukkit.getOnlinePlayers()) {
            p.sendMessage(cancelMsg);
            try {
                p.playSound(p.getLocation(), Sound.ENTITY_EXPERIENCE_ORB_PICKUP, 1.0f, 1.0f);
            }
            catch (Exception exception) {}
        }
    }

    public void extendMaintenanceCountdown(int additionalSec) {
        if (this.maintenanceCountdownTask == null || this.countdownRemaining <= 0) {
            return;
        }
        this.countdownRemaining += additionalSec;
        String addStr = additionalSec >= 60 ? additionalSec / 60 + " \u043c\u0438\u043d." : additionalSec + " \u0441\u0435\u043a.";
        Component extMsg = MiniMessage.miniMessage().deserialize(("<gradient:#FFB800:#FFA500>\u23f1 [\u0412\u041d\u0418\u041c\u0410\u041d\u0418\u0415]</gradient> <yellow>\u0410\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0442\u043e\u0440 \u0434\u043e\u0431\u0430\u0432\u0438\u043b <bold>+" + addStr + "</bold> \u043a \u0442\u0430\u0439\u043c\u0435\u0440\u0443!</yellow>"));
        for (Player p : Bukkit.getOnlinePlayers()) {
            p.sendMessage(extMsg);
            try {
                p.playSound(p.getLocation(), Sound.BLOCK_NOTE_BLOCK_BELL, 1.0f, 1.0f);
            }
            catch (Exception exception) {}
        }
    }

    public void startMaintenanceCountdown(String mode, int totalSec, String reason) {
        boolean isRestart;
        String actionName;
        if (this.maintenanceCountdownTask != null) {
            this.maintenanceCountdownTask.cancel();
            this.maintenanceCountdownTask = null;
        }
        String string = actionName = (isRestart = "restart".equalsIgnoreCase(mode)) ? "\u0440\u0435\u0441\u0442\u0430\u0440\u0442\u0430" : "\u0442\u0435\u0445\u0440\u0430\u0431\u043e\u0442";
        String actualReason = reason != null && !reason.trim().isEmpty() ? reason.trim() : (isRestart ? "\u041f\u043b\u0430\u043d\u043e\u0432\u0430\u044f \u043f\u0435\u0440\u0435\u0437\u0430\u0433\u0440\u0443\u0437\u043a\u0430 \u0441\u0435\u0440\u0432\u0435\u0440\u0430" : "\u0422\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u043e\u0435 \u043e\u0431\u0441\u043b\u0443\u0436\u0438\u0432\u0430\u043d\u0438\u0435 \u0441\u0435\u0440\u0432\u0435\u0440\u0430");
        final String safeReason = MiniMessage.miniMessage().escapeTags(actualReason);
        this.countdownRemaining = totalSec;
        this.countdownMode = mode;
        this.countdownReason = actualReason;
        String initTimeStr = totalSec >= 60 ? totalSec / 60 + " \u043c\u0438\u043d." : totalSec + " \u0441\u0435\u043a.";
        Component banner = MiniMessage.miniMessage().deserialize(("\n<gradient:#FFA500:#FF7700>\u2726 \u2500\u2500 \u23f1 \u041e\u0411\u042a\u042f\u0412\u041b\u0415\u041d\u0418\u0415 " + (isRestart ? "\u041e \u0420\u0415\u0421\u0422\u0410\u0420\u0422\u0415" : "\u041e \u0422\u0415\u0425\u0420\u0410\u0411\u041e\u0422\u0410\u0425") + " \u2500\u2500 \u2726</gradient>\n  <yellow>\u0414\u043e " + actionName + " \u043e\u0441\u0442\u0430\u043b\u043e\u0441\u044c: <bold>" + initTimeStr + "</bold></yellow>\n  <gray>\u041f\u0440\u0438\u0447\u0438\u043d\u0430: <white>" + safeReason + "</white></gray>\n<gradient:#FFA500:#FF7700>\u2726 \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 \u2726</gradient>\n"));
        for (Player p : Bukkit.getOnlinePlayers()) {
            p.sendMessage(banner);
            try {
                p.playSound(p.getLocation(), Sound.BLOCK_NOTE_BLOCK_BELL, 1.0f, 1.0f);
            }
            catch (Exception exception) {}
        }
        this.maintenanceCountdownTask = new BukkitRunnable(){
            final VanillaBridge this$0 = VanillaBridge.this;

            public void run() {
                if (this.this$0.countdownRemaining <= 0) {
                    this.cancel();
                    this.this$0.maintenanceCountdownTask = null;
                    if (isRestart) {
                        for (Player p : Bukkit.getOnlinePlayers()) {
                            p.sendTitle("\u00a7a\u00a7l\u041f\u0415\u0420\u0415\u0417\u0410\u0413\u0420\u0423\u0417\u041a\u0410", "\u00a7f\u0421\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u0438\u0435 \u043c\u0438\u0440\u0430...", 0, 40, 20);
                        }
                        Bukkit.dispatchCommand((CommandSender)Bukkit.getConsoleSender(), (String)"save-all");
                        Component kickComp = MiniMessage.miniMessage().deserialize("<gradient:#ff7a00:#ffae19><bold>Vanilla Land</bold></gradient> <dark_gray>\u2502</dark_gray> <green>\u041f\u0435\u0440\u0435\u0437\u0430\u0433\u0440\u0443\u0437\u043a\u0430 \u0441\u0435\u0440\u0432\u0435\u0440\u0430</green>\n\n<gray>\u0421\u0435\u0440\u0432\u0435\u0440 \u043f\u0435\u0440\u0435\u0437\u0430\u0433\u0440\u0443\u0436\u0430\u0435\u0442\u0441\u044f \u0434\u043b\u044f \u043f\u0440\u0438\u043c\u0435\u043d\u0435\u043d\u0438\u044f \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u0439.\n<white>\u0412\u044b \u0441\u043c\u043e\u0436\u0435\u0442\u0435 \u0437\u0430\u0439\u0442\u0438 \u043e\u0431\u0440\u0430\u0442\u043d\u043e \u0447\u0435\u0440\u0435\u0437 1-2 \u043c\u0438\u043d\u0443\u0442\u044b!</white>\n\n<gradient:#00AAFF:#0055FF>\ud83d\uded2 \u0414\u043e\u043d\u0430\u0442:</gradient> <white>vanillaland.store</white>\n<gradient:#FFA500:#FF5500>\ud83c\udf10 \u0421\u0430\u0439\u0442:</gradient> <white>vanillaland.fun</white>\n<gradient:#0088cc:#29b6f6>\u2708 Telegram:</gradient> <white>t.me/vanilandes</white>\n<gradient:#ff7a00:#ffae19>\ud83d\udcac Discord:</gradient> <white>discord.gg/Ba5cMK7F6a</white>");
                        for (Player p : Bukkit.getOnlinePlayers()) {
                            p.kick(kickComp);
                        }
                        Bukkit.getScheduler().runTaskLater((Plugin)this.this$0, () -> {
                            try {
                                Bukkit.spigot().restart();
                            }
                            catch (Throwable t) {
                                Bukkit.shutdown();
                            }
                        }, 20L);
                    } else {
                        this.this$0.maintenance = true;
                        this.this$0.maintenanceReason = this.this$0.countdownReason;
                        Component kickComp = MiniMessage.miniMessage().deserialize(("<gradient:#FFA500:#FF7700><bold>Vanilla Land</bold></gradient> <dark_gray>\u2502</dark_gray> <red>\u0422\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u0438\u0435 \u0440\u0430\u0431\u043e\u0442\u044b</red>\n\n<gray>\u0421\u0435\u0440\u0432\u0435\u0440 \u0432\u0440\u0435\u043c\u0435\u043d\u043d\u043e \u0437\u0430\u043a\u0440\u044b\u0442 \u043d\u0430 \u043e\u0431\u0441\u043b\u0443\u0436\u0438\u0432\u0430\u043d\u0438\u0435:\n<white>" + safeReason + "</white>\n\n<gradient:#00AAFF:#0055FF>\ud83d\uded2 \u0414\u043e\u043d\u0430\u0442:</gradient> <white>vanillaland.store</white>\n<gradient:#FFA500:#FF5500>\ud83c\udf10 \u0421\u0430\u0439\u0442:</gradient> <white>vanillaland.fun</white>\n<gradient:#0088cc:#29b6f6>\u2708 Telegram:</gradient> <white>t.me/vanilandes</white>\n<gradient:#ff7a00:#ffae19>\ud83d\udcac Discord:</gradient> <white>discord.gg/Ba5cMK7F6a</white>"));
                        for (Player p : Bukkit.getOnlinePlayers()) {
                            if (p.isOp() || p.hasPermission("vanillabridge.admin") || this.this$0.isStaff(p.getName())) continue;
                            p.kick(kickComp);
                        }
                    }
                    return;
                }
                int mins = this.this$0.countdownRemaining / 60;
                int secs = this.this$0.countdownRemaining % 60;
                Component barComp = this.this$0.countdownRemaining > 60 ? MiniMessage.miniMessage().deserialize(String.format(Locale.US, "<gradient:#ff7a00:#ffae19><bold>\u23f1 \u0414\u043e %s: %02d:%02d</bold></gradient> <dark_gray>\u2502</dark_gray> <gray>%s</gray>", actionName, mins, secs, safeReason)) : (this.this$0.countdownRemaining >= 15 ? MiniMessage.miniMessage().deserialize(String.format(Locale.US, "<gradient:#FFB800:#FFA500><bold>\u23f1 \u0414\u043e %s: %02d:%02d</bold></gradient> <dark_gray>\u2502</dark_gray> <gray>%s</gray>", actionName, mins, secs, safeReason)) : MiniMessage.miniMessage().deserialize(String.format(Locale.US, "<gradient:#ff7a00:#ffae19><bold>\u23f1 \u0414\u043e %s: %02d:%02d</bold></gradient> <dark_gray>\u2502</dark_gray> <yellow>\u041f\u0440\u0438\u0433\u043e\u0442\u043e\u0432\u044c\u0442\u0435\u0441\u044c!</yellow>", actionName, mins, secs)));
                for (Player p : Bukkit.getOnlinePlayers()) {
                    p.sendActionBar(barComp);
                    if (this.this$0.countdownRemaining <= 15) {
                        p.addPotionEffect(new PotionEffect(PotionEffectType.RESISTANCE, 40, 4, false, false));
                    }
                    if (this.this$0.countdownRemaining <= 5) {
                        try {
                            float pitch = 1.0f + (float)(6 - this.this$0.countdownRemaining) * 0.2f;
                            p.playSound(p.getLocation(), Sound.BLOCK_NOTE_BLOCK_BELL, 1.0f, pitch);
                        }
                        catch (Exception exception) {}
                        continue;
                    }
                    if (this.this$0.countdownRemaining != 10 && this.this$0.countdownRemaining != 30 && this.this$0.countdownRemaining != 60) continue;
                    try {
                        p.playSound(p.getLocation(), Sound.BLOCK_NOTE_BLOCK_PLING, 1.0f, 1.0f);
                    }
                    catch (Exception exception) {}
                }
                if (this.this$0.countdownRemaining == 60 || this.this$0.countdownRemaining == 30) {
                    String timeLabel = this.this$0.countdownRemaining == 60 ? "1 \u043c\u0438\u043d\u0443\u0442\u0430" : "30 \u0441\u0435\u043a\u0443\u043d\u0434";
                    Component remComp = MiniMessage.miniMessage().deserialize(("<gradient:#FFB800:#FFA500>\u23f1 [Vanilla Land]</gradient> <yellow>\u0414\u043e " + actionName + " \u043e\u0441\u0442\u0430\u043b\u0430\u0441\u044c <bold>" + timeLabel + "</bold>!</yellow>"));
                    for (Player p : Bukkit.getOnlinePlayers()) {
                        p.sendMessage(remComp);
                    }
                }
                --this.this$0.countdownRemaining;
            }
        }.runTaskTimer((Plugin)this, 20L, 20L);
    }

    public void handleIncomingMessage(String rawJson) {
        Component prefixComponent;
        String type = this.extractField(rawJson, "type");
        if ("dm".equalsIgnoreCase(type)) {
            String target = this.extractField(rawJson, "target");
            String author = this.extractField(rawJson, "author");
            String authorId = this.extractField(rawJson, "author_id");
            String content = this.extractField(rawJson, "content");
            if (target.isEmpty() || content.isEmpty()) {
                return;
            }
            Bukkit.getScheduler().runTask((Plugin)this, () -> {
                Player p = Bukkit.getPlayerExact((String)target);
                if (p == null) {
                    for (Player online : Bukkit.getOnlinePlayers()) {
                        if (!online.getName().equalsIgnoreCase(target)) continue;
                        p = online;
                        break;
                    }
                }
                if (p != null && p.isOnline()) {
                    this.lastDiscordDmSender.put(p.getUniqueId(), authorId);
                    this.lastDiscordDmAuthor.put(p.getUniqueId(), author);
                    String safeAuthor = MiniMessage.miniMessage().escapeTags(author);
                    String safeContent = MiniMessage.miniMessage().escapeTags(content);
                    String dmMsg = "<gradient:#ff7a00:#ffae19>\u2709 Discord \u041b\u0421</gradient> <dark_gray>\u2502</dark_gray> <white><hover:show_text:'&7\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c Discord: &f" + safeAuthor + "'>" + safeAuthor + "</hover></white> <gradient:#FFA500:#FF7700>\u2192</gradient> <gray>\u0412\u0430\u043c:</gray> <white>" + safeContent + "</white>";
                    String hintMsg = "<dark_gray>\u21b3 <gray>\u041d\u0430\u0436\u043c\u0438\u0442\u0435 <hover:show_text:'&e\u041a\u043b\u0438\u043a: \u043f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u0438\u0442\u044c \u043e\u0442\u0432\u0435\u0442 " + safeAuthor + " \u0432 Discord'><click:suggest_command:'/rd '><gradient:#FFA500:#FF7700>/rd [\u0442\u0435\u043a\u0441\u0442]</gradient></click></hover> \u0434\u043b\u044f \u043e\u0442\u0432\u0435\u0442\u0430</gray>";
                    p.sendMessage(MiniMessage.miniMessage().deserialize(dmMsg));
                    p.sendMessage(MiniMessage.miniMessage().deserialize(hintMsg));
                    try {
                        p.playSound(p.getLocation(), Sound.BLOCK_NOTE_BLOCK_PLING, 1.0f, 1.8f);
                    }
                    catch (Exception exception) {}
                } else if (this.bridgeClient != null && this.bridgeClient.isConnected()) {
                    this.bridgeClient.send(String.format(Locale.US, "{\"type\":\"dm_error\",\"target_id\":\"%s\",\"player\":\"%s\",\"reason\":\"offline\"}", VanillaBridge.escapeJson(authorId), VanillaBridge.escapeJson(target)));
                }
            });
            return;
        }
        if ("announce".equalsIgnoreCase(type)) {
            String text = this.extractField(rawJson, "text");
            String author = this.extractField(rawJson, "author");
            if (author.isEmpty()) {
                author = "Discord";
            }
            this.broadcastAnnouncement(text, author, false);
            return;
        }
        if ("query_world".equalsIgnoreCase(type)) {
            String queryId = this.extractField(rawJson, "query_id");
            Bukkit.getScheduler().runTask((Plugin)this, () -> {
                World w;
                World world = w = Bukkit.getWorlds().isEmpty() ? null : (World)Bukkit.getWorlds().get(0);
                if (w != null && this.bridgeClient != null && this.bridgeClient.isConnected()) {
                    long time = w.getTime();
                    long fullTime = w.getFullTime();
                    long day = fullTime / 24000L;
                    boolean isThundering = w.isThundering();
                    boolean hasStorm = w.hasStorm();
                    String weather = isThundering ? "thunder" : (hasStorm ? "rain" : "clear");
                    int moonPhase = (int)(day % 8L);
                    String resp = String.format(Locale.US, "{\"type\":\"world_data\",\"query_id\":\"%s\",\"time\":%d,\"day\":%d,\"weather\":\"%s\",\"moon_phase\":%d}", VanillaBridge.escapeJson(queryId), time, day, weather, moonPhase);
                    this.bridgeClient.send(resp);
                }
            });
            return;
        }
        if ("query_player".equalsIgnoreCase(type)) {
            String queryId = this.extractField(rawJson, "query_id");
            String target = this.extractField(rawJson, "player");
            Bukkit.getScheduler().runTask((Plugin)this, () -> {
                Player p = Bukkit.getPlayerExact((String)target);
                if (p == null) {
                    for (Player pl : Bukkit.getOnlinePlayers()) {
                        if (!pl.getName().equalsIgnoreCase(target)) continue;
                        p = pl;
                        break;
                    }
                }
                if (p != null && this.bridgeClient != null && this.bridgeClient.isConnected()) {
                    String world = p.getWorld().getName();
                    int x = p.getLocation().getBlockX();
                    int y = p.getLocation().getBlockY();
                    int z = p.getLocation().getBlockZ();
                    double hp = p.getHealth();
                    double maxHp = p.getMaxHealth();
                    int food = p.getFoodLevel();
                    int level = p.getLevel();
                    int ping = p.getPing();
                    String ip = p.getAddress() != null && p.getAddress().getAddress() != null ? p.getAddress().getAddress().getHostAddress() : "N/A";
                    String gamemode = p.getGameMode().name();
                    String helmet = p.getInventory().getHelmet() != null ? p.getInventory().getHelmet().getType().name() : "AIR";
                    String chestplate = p.getInventory().getChestplate() != null ? p.getInventory().getChestplate().getType().name() : "AIR";
                    String leggings = p.getInventory().getLeggings() != null ? p.getInventory().getLeggings().getType().name() : "AIR";
                    String boots = p.getInventory().getBoots() != null ? p.getInventory().getBoots().getType().name() : "AIR";
                    String mainHand = p.getInventory().getItemInMainHand().getType().name();
                    String offHand = p.getInventory().getItemInOffHand().getType().name();
                    String skinHash = VanillaBridge.extractSkinHash(p.getPlayerProfile());
                    if (skinHash.isEmpty()) {
                        skinHash = this.getCachedPlayerSkin(p.getName());
                    } else {
                        this.cachePlayerSkin(p.getName(), skinHash);
                    }
                    int playtime = p.getStatistic(Statistic.PLAY_ONE_MINUTE);
                    int diamonds = VanillaBridge.getSafeMineStat((OfflinePlayer)p, Material.DIAMOND_ORE) + VanillaBridge.getSafeMineStat((OfflinePlayer)p, Material.DEEPSLATE_DIAMOND_ORE);
                    int debris = VanillaBridge.getSafeMineStat((OfflinePlayer)p, Material.ANCIENT_DEBRIS);
                    int emeralds = VanillaBridge.getSafeMineStat((OfflinePlayer)p, Material.EMERALD_ORE) + VanillaBridge.getSafeMineStat((OfflinePlayer)p, Material.DEEPSLATE_EMERALD_ORE);
                    int gold = VanillaBridge.getSafeMineStat((OfflinePlayer)p, Material.GOLD_ORE) + VanillaBridge.getSafeMineStat((OfflinePlayer)p, Material.DEEPSLATE_GOLD_ORE) + VanillaBridge.getSafeMineStat((OfflinePlayer)p, Material.NETHER_GOLD_ORE);
                    int iron = VanillaBridge.getSafeMineStat((OfflinePlayer)p, Material.IRON_ORE) + VanillaBridge.getSafeMineStat((OfflinePlayer)p, Material.DEEPSLATE_IRON_ORE);
                    int kills = p.getStatistic(Statistic.PLAYER_KILLS);
                    int deaths = p.getStatistic(Statistic.DEATHS);
                    int mobKills = p.getStatistic(Statistic.MOB_KILLS);
                    long firstPlayed = p.getFirstPlayed();
                    long lastPlayed = p.getLastPlayed();
                    StringBuilder invSb = new StringBuilder("[");
                    boolean first = true;
                    for (int slot = 0; slot < 36; ++slot) {
                        ItemStack item = p.getInventory().getItem(slot);
                        String serialized = this.serializeItemStack(item, slot);
                        if (serialized == null) continue;
                        if (!first) {
                            invSb.append(",");
                        }
                        invSb.append(serialized);
                        first = false;
                    }
                    invSb.append("]");
                    StringBuilder enderSb = new StringBuilder("[");
                    first = true;
                    for (int slot = 0; slot < 27; ++slot) {
                        ItemStack item = p.getEnderChest().getItem(slot);
                        String serialized = this.serializeItemStack(item, slot);
                        if (serialized == null) continue;
                        if (!first) {
                            enderSb.append(",");
                        }
                        enderSb.append(serialized);
                        first = false;
                    }
                    enderSb.append("]");
                    StringBuilder effSb = new StringBuilder("[");
                    first = true;
                    for (PotionEffect eff : p.getActivePotionEffects()) {
                        if (!first) {
                            effSb.append(",");
                        }
                        effSb.append(String.format(Locale.US, "\"%s %d (%ds)\"", eff.getType().getName(), eff.getAmplifier() + 1, eff.getDuration() / 20));
                        first = false;
                    }
                    effSb.append("]");
                    String resp = String.format(Locale.US, "{\"type\":\"player_data\",\"query_id\":\"%s\",\"player\":\"%s\",\"uuid\":\"%s\",\"online\":true,\"skin\":\"%s\",\"first_played\":%d,\"last_played\":%d,\"playtime\":%d,\"diamonds\":%d,\"debris\":%d,\"emeralds\":%d,\"gold\":%d,\"iron\":%d,\"kills\":%d,\"deaths\":%d,\"mob_kills\":%d,\"world\":\"%s\",\"x\":%d,\"y\":%d,\"z\":%d,\"hp\":%.1f,\"max_hp\":%.1f,\"food\":%d,\"level\":%d,\"ping\":%d,\"ip\":\"%s\",\"gamemode\":\"%s\",\"helmet\":\"%s\",\"chestplate\":\"%s\",\"leggings\":\"%s\",\"boots\":\"%s\",\"main_hand\":\"%s\",\"off_hand\":\"%s\",\"inventory\":%s,\"ender\":%s,\"effects\":%s}", VanillaBridge.escapeJson(queryId), VanillaBridge.escapeJson(p.getName()), p.getUniqueId().toString(), VanillaBridge.escapeJson(skinHash), firstPlayed, lastPlayed, playtime, diamonds, debris, emeralds, gold, iron, kills, deaths, mobKills, VanillaBridge.escapeJson(world), x, y, z, hp, maxHp, food, level, ping, VanillaBridge.escapeJson(ip), gamemode, helmet, chestplate, leggings, boots, mainHand, offHand, invSb.toString(), enderSb.toString(), effSb.toString());
                    this.bridgeClient.send(resp);
                } else if (this.bridgeClient != null && this.bridgeClient.isConnected()) {
                    Bukkit.getScheduler().runTaskAsynchronously((Plugin)this, () -> {
                        try {
                            OfflinePlayer op = Bukkit.getOfflinePlayerIfCached((String)target);
                            if (op == null) {
                                for (OfflinePlayer o : Bukkit.getOfflinePlayers()) {
                                    if (o.getName() == null || !o.getName().equalsIgnoreCase(target)) continue;
                                    op = o;
                                    break;
                                }
                            }
                            if (op == null) {
                                op = Bukkit.getOfflinePlayer((String)target);
                            }
                            String actualName = op.getName() != null && !op.getName().isEmpty() ? op.getName() : target;
                            String uuid = op.getUniqueId().toString();
                            long firstPlayed = op.getFirstPlayed();
                            long lastPlayed = op.getLastPlayed();
                            boolean hasPlayed = op.hasPlayedBefore();
                            String skinHash = this.getCachedPlayerSkin(actualName);
                            if (skinHash.isEmpty() && hasPlayed) {
                                try {
                                    PlayerProfile prof = op.getPlayerProfile();
                                    if (prof.hasTextures() && !(skinHash = VanillaBridge.extractSkinHash(prof)).isEmpty()) {
                                        this.cachePlayerSkin(actualName, skinHash);
                                    }
                                }
                                catch (Throwable prof) {
                                    // empty catch block
                                }
                            }
                            int playtime = 0;
                            int diamonds = 0;
                            int debris = 0;
                            int emeralds = 0;
                            int gold = 0;
                            int iron = 0;
                            int kills = 0;
                            int deaths = 0;
                            int mobKills = 0;
                            if (hasPlayed) {
                                try {
                                    playtime = op.getStatistic(Statistic.PLAY_ONE_MINUTE);
                                    diamonds = VanillaBridge.getSafeMineStat(op, Material.DIAMOND_ORE) + VanillaBridge.getSafeMineStat(op, Material.DEEPSLATE_DIAMOND_ORE);
                                    debris = VanillaBridge.getSafeMineStat(op, Material.ANCIENT_DEBRIS);
                                    emeralds = VanillaBridge.getSafeMineStat(op, Material.EMERALD_ORE) + VanillaBridge.getSafeMineStat(op, Material.DEEPSLATE_EMERALD_ORE);
                                    gold = VanillaBridge.getSafeMineStat(op, Material.GOLD_ORE) + VanillaBridge.getSafeMineStat(op, Material.DEEPSLATE_GOLD_ORE) + VanillaBridge.getSafeMineStat(op, Material.NETHER_GOLD_ORE);
                                    iron = VanillaBridge.getSafeMineStat(op, Material.IRON_ORE) + VanillaBridge.getSafeMineStat(op, Material.DEEPSLATE_IRON_ORE);
                                    kills = op.getStatistic(Statistic.PLAYER_KILLS);
                                    deaths = op.getStatistic(Statistic.DEATHS);
                                    mobKills = op.getStatistic(Statistic.MOB_KILLS);
                                }
                                catch (Throwable throwable) {
                                    // empty catch block
                                }
                            }
                            String resp = String.format(Locale.US, "{\"type\":\"player_data\",\"query_id\":\"%s\",\"player\":\"%s\",\"uuid\":\"%s\",\"online\":false,\"found\":%b,\"skin\":\"%s\",\"first_played\":%d,\"last_played\":%d,\"playtime\":%d,\"diamonds\":%d,\"debris\":%d,\"emeralds\":%d,\"gold\":%d,\"iron\":%d,\"kills\":%d,\"deaths\":%d,\"mob_kills\":%d}", VanillaBridge.escapeJson(queryId), VanillaBridge.escapeJson(actualName), uuid, hasPlayed, VanillaBridge.escapeJson(skinHash), firstPlayed, lastPlayed, playtime, diamonds, debris, emeralds, gold, iron, kills, deaths, mobKills);
                            this.bridgeClient.send(resp);
                        }
                        catch (Exception e) {
                            String errResp = String.format(Locale.US, "{\"type\":\"player_data\",\"query_id\":\"%s\",\"player\":\"%s\",\"online\":false,\"found\":false}", VanillaBridge.escapeJson(queryId), VanillaBridge.escapeJson(target));
                            this.bridgeClient.send(errResp);
                        }
                    });
                }
            });
            return;
        }
        if ("query_top".equalsIgnoreCase(type)) {
            String queryId = this.extractField(rawJson, "query_id");
            long now = System.currentTimeMillis();
            if (this.cachedTopJson != null && now - this.lastTopCacheTime < 300000L) {
                String cached = this.cachedTopJson.replace("\"%QUERY_ID%\"", "\"" + VanillaBridge.escapeJson(queryId) + "\"");
                if (this.bridgeClient != null && this.bridgeClient.isConnected()) {
                    this.bridgeClient.send(cached);
                }
                return;
            }
            Bukkit.getScheduler().runTaskAsynchronously((Plugin)this, () -> {
                this.updateTopCache();
                if (this.cachedTopJson != null && this.bridgeClient != null && this.bridgeClient.isConnected()) {
                    String toSend = this.cachedTopJson.replace("\"%QUERY_ID%\"", "\"" + VanillaBridge.escapeJson(queryId) + "\"");
                    this.bridgeClient.send(toSend);
                }
            });
            return;
        }
        if ("query_chunks".equalsIgnoreCase(type)) {
            String queryId = this.extractField(rawJson, "query_id");
            Bukkit.getScheduler().runTask((Plugin)this, () -> {
                if (this.bridgeClient != null && this.bridgeClient.isConnected()) {
                    StringBuilder worldsSb = new StringBuilder("[");
                    boolean firstW = true;
                    int totalChunks = 0;
                    int totalEntities = 0;
                    int totalMonsters = 0;
                    int totalAnimals = 0;
                    int totalItems = 0;
                    int totalMisc = 0;
                    class HotChunk {
                        final String world;
                        final int cx;
                        final int cz;
                        final int count;
                        final int bx;
                        final int bz;
                        final String nearest;

                        HotChunk(VanillaBridge this$0, String world, int cx, int cz, int count, int bx, int bz, String nearest) {
                            this.world = world;
                            this.cx = cx;
                            this.cz = cz;
                            this.count = count;
                            this.bx = bx;
                            this.bz = bz;
                            this.nearest = nearest;
                        }
                    }
                    ArrayList<HotChunk> allHotChunks = new ArrayList<HotChunk>();
                    for (World w : Bukkit.getWorlds()) {
                        int chunks = w.getLoadedChunks().length;
                        List entities = w.getEntities();
                        int entSize = entities.size();
                        totalChunks += chunks;
                        totalEntities += entSize;
                        int wMonsters = 0;
                        int wAnimals = 0;
                        int wItems = 0;
                        int wMisc = 0;
                        HashMap<Chunk, Integer> chunkCounts = new HashMap<Chunk, Integer>();
                        for (org.bukkit.entity.Entity e : (java.util.List<org.bukkit.entity.Entity>)(java.util.List<?>)entities) {
                            if (e instanceof Monster) {
                                ++wMonsters;
                            } else if (e instanceof Animals) {
                                ++wAnimals;
                            } else if (e instanceof Item) {
                                ++wItems;
                            } else {
                                ++wMisc;
                            }
                            Chunk c = e.getLocation().getChunk();
                            chunkCounts.merge(c, 1, Integer::sum);
                        }
                        totalMonsters += wMonsters;
                        totalAnimals += wAnimals;
                        totalItems += wItems;
                        totalMisc += wMisc;
                        ArrayList<Map.Entry<Chunk, Integer>> sorted = new ArrayList<>(chunkCounts.entrySet());
                        sorted.sort((a, b) -> Integer.compare(b.getValue(), a.getValue()));
                        for (int i = 0; i < Math.min(3, sorted.size()); ++i) {
                            Map.Entry entry = (Map.Entry)sorted.get(i);
                            if ((Integer)entry.getValue() < 8) continue;
                            Chunk c = (Chunk)entry.getKey();
                            int bx = c.getX() * 16 + 8;
                            int bz = c.getZ() * 16 + 8;
                            String nearestName = "\u041d\u0438\u043a\u043e\u0433\u043e";
                            double minDist = 65536.0;
                            Location cLoc = new Location(w, (double)bx, 64.0, (double)bz);
                            for (Player p : w.getPlayers()) {
                                double d = p.getLocation().distanceSquared(cLoc);
                                if (!(d < minDist)) continue;
                                minDist = d;
                                nearestName = p.getName();
                            }
                            allHotChunks.add(new HotChunk(this, w.getName(), c.getX(), c.getZ(), (Integer)entry.getValue(), bx, bz, nearestName));
                        }
                        String dragonField = "";
                        if (w.getEnvironment() == World.Environment.THE_END) {
                            try {
                                DragonBattle db = w.getEnderDragonBattle();
                                if (db != null) {
                                    String ds = db.getEnderDragon() != null ? "\u0416\u0438\u0432" : (db.getRespawnPhase() != null && db.getRespawnPhase() != DragonBattle.RespawnPhase.NONE ? "\u0412\u043e\u0437\u0440\u043e\u0436\u0434\u0430\u0435\u0442\u0441\u044f" : (db.hasBeenPreviouslyKilled() ? "\u0423\u0431\u0438\u0442" : "\u041d\u0435 \u043f\u043e\u0431\u0435\u0436\u0434\u0451\u043d"));
                                    dragonField = String.format(Locale.US, ",\"dragon_status\":\"%s\"", VanillaBridge.escapeJson(ds));
                                }
                            }
                            catch (Throwable throwable) {
                                // empty catch block
                            }
                        }
                        if (!firstW) {
                            worldsSb.append(",");
                        }
                        worldsSb.append(String.format(Locale.US, "{\"name\":\"%s\",\"chunks\":%d,\"entities\":%d,\"monsters\":%d,\"animals\":%d,\"items\":%d,\"misc\":%d%s}", VanillaBridge.escapeJson(w.getName()), chunks, entSize, wMonsters, wAnimals, wItems, wMisc, dragonField));
                        firstW = false;
                    }
                    worldsSb.append("]");
                    allHotChunks.sort((a, b) -> Integer.compare(b.count, a.count));
                    StringBuilder hotSb = new StringBuilder("[");
                    boolean firstH = true;
                    for (int i = 0; i < Math.min(5, allHotChunks.size()); ++i) {
                        HotChunk hc = (HotChunk)allHotChunks.get(i);
                        if (!firstH) {
                            hotSb.append(",");
                        }
                        hotSb.append(String.format(Locale.US, "{\"world\":\"%s\",\"chunk_x\":%d,\"chunk_z\":%d,\"block_x\":%d,\"block_z\":%d,\"count\":%d,\"nearest\":\"%s\"}", VanillaBridge.escapeJson(hc.world), hc.cx, hc.cz, hc.bx, hc.bz, hc.count, VanillaBridge.escapeJson(hc.nearest)));
                        firstH = false;
                    }
                    hotSb.append("]");
                    String resp = String.format(Locale.US, "{\"type\":\"chunks_data\",\"query_id\":\"%s\",\"total_chunks\":%d,\"total_entities\":%d,\"total_monsters\":%d,\"total_animals\":%d,\"total_items\":%d,\"total_misc\":%d,\"worlds\":%s,\"hot_chunks\":%s}", VanillaBridge.escapeJson(queryId), totalChunks, totalEntities, totalMonsters, totalAnimals, totalItems, totalMisc, worldsSb.toString(), hotSb.toString());
                    this.bridgeClient.send(resp);
                }
            });
            return;
        }
        if ("maintenance".equalsIgnoreCase(type)) {
            String enabledStr = this.extractField(rawJson, "enabled");
            boolean enabled = "true".equalsIgnoreCase(enabledStr);
            String reason = this.extractField(rawJson, "reason");
            if (reason.isEmpty()) {
                reason = "\u0422\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u043e\u0435 \u043e\u0431\u0441\u043b\u0443\u0436\u0438\u0432\u0430\u043d\u0438\u0435 \u0441\u0435\u0440\u0432\u0435\u0440\u0430";
            }
            this.maintenance = enabled;
            this.maintenanceReason = reason;
            if (enabled) {
                String safeReason = MiniMessage.miniMessage().escapeTags(reason);
                Component kickComp = MiniMessage.miniMessage().deserialize(("<gradient:#FFA500:#FF7700><bold>Vanilla Land</bold></gradient> <dark_gray>\u2502</dark_gray> <red>\u0422\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u0438\u0435 \u0440\u0430\u0431\u043e\u0442\u044b</red>\n\n<gray>\u0421\u0435\u0440\u0432\u0435\u0440 \u0432\u0440\u0435\u043c\u0435\u043d\u043d\u043e \u0437\u0430\u043a\u0440\u044b\u0442 \u043d\u0430 \u043e\u0431\u0441\u043b\u0443\u0436\u0438\u0432\u0430\u043d\u0438\u0435:\n<white>" + safeReason + "</white>\n\n<gradient:#00AAFF:#0055FF>\ud83d\uded2 \u0414\u043e\u043d\u0430\u0442:</gradient> <white>vanillaland.store</white>\n<gradient:#FFA500:#FF5500>\ud83c\udf10 \u0421\u0430\u0439\u0442:</gradient> <white>vanillaland.fun</white>\n<gradient:#0088cc:#29b6f6>\u2708 Telegram:</gradient> <white>t.me/vanilandes</white>\n<gradient:#ff7a00:#ffae19>\ud83d\udcac Discord:</gradient> <white>discord.gg/Ba5cMK7F6a</white>"));
                for (Player p : Bukkit.getOnlinePlayers()) {
                    if (p.isOp() || p.hasPermission("vanillabridge.admin") || this.isStaff(p.getName())) continue;
                    p.kick(kickComp);
                }
            } else {
                this.cancelMaintenanceCountdown();
            }
            return;
        }
        if ("maintenance_countdown_cancel".equalsIgnoreCase(type)) {
            this.cancelMaintenanceCountdown();
            return;
        }
        if ("maintenance_countdown_extend".equalsIgnoreCase(type)) {
            String secStr = this.extractField(rawJson, "seconds");
            int extSec = 60;
            try {
                if (!secStr.isEmpty()) {
                    extSec = Integer.parseInt(secStr);
                }
            }
            catch (Exception reason) {
                // empty catch block
            }
            this.extendMaintenanceCountdown(extSec);
            return;
        }
        if ("maintenance_countdown".equalsIgnoreCase(type)) {
            String mode = this.extractField(rawJson, "mode");
            String secStr = this.extractField(rawJson, "seconds");
            String reason = this.extractField(rawJson, "reason");
            if (reason.isEmpty()) {
                reason = "\u041f\u043b\u0430\u043d\u043e\u0432\u044b\u0435 \u0440\u0430\u0431\u043e\u0442\u044b \u043d\u0430 \u0441\u0435\u0440\u0432\u0435\u0440\u0435";
            }
            int totalSec = 180;
            try {
                if (!secStr.isEmpty()) {
                    totalSec = Integer.parseInt(secStr);
                }
            }
            catch (Exception kickComp) {
                // empty catch block
            }
            this.startMaintenanceCountdown(mode, totalSec, reason);
            return;
        }
        if ("sync_staff".equalsIgnoreCase(type)) {
            int start = rawJson.indexOf("\"staff\"");
            if (start != -1) {
                int open = rawJson.indexOf(91, start);
                int close = rawJson.indexOf(93, open);
                if (open != -1 && close != -1) {
                    String arr = rawJson.substring(open + 1, close);
                    ArrayList<String> staffList = new ArrayList<String>();
                    for (String item : arr.split(",")) {
                        String clean = item.replace("\"", "").trim();
                        if (clean.isEmpty()) continue;
                        staffList.add(clean);
                    }
                    this.updateStaffWhitelist(staffList);
                }
            }
            return;
        }
        if ("emergency_kick".equalsIgnoreCase(type)) {
            String targetPlayer = this.extractField(rawJson, "player");
            Player p = Bukkit.getPlayerExact((String)targetPlayer);
            if (p != null && p.isOnline()) {
                Bukkit.getScheduler().runTask((Plugin)this, () -> {
                    if (p.isOnline()) {
                        p.kick(MiniMessage.miniMessage().deserialize("<gradient:#ff7a00:#ffae19><bold>Vanilla Land</bold></gradient> <dark_gray>\u2502</dark_gray> <red>\u042d\u043a\u0441\u0442\u0440\u0435\u043d\u043d\u0430\u044f \u0431\u043b\u043e\u043a\u0438\u0440\u043e\u0432\u043a\u0430</red>\n\n<red>\u0412\u043b\u0430\u0434\u0435\u043b\u0435\u0446 \u0430\u043a\u043a\u0430\u0443\u043d\u0442\u0430 \u043d\u0430\u0436\u0430\u043b \u043a\u043d\u043e\u043f\u043a\u0443 \u044d\u043a\u0441\u0442\u0440\u0435\u043d\u043d\u043e\u0433\u043e \u043a\u0438\u043a\u0430 \u0432 Discord!\n<gray>\u0412\u0441\u0435 \u0434\u043e\u0432\u0435\u0440\u0435\u043d\u043d\u044b\u0435 \u0441\u0435\u0441\u0441\u0438\u0438 IP \u0441\u0431\u0440\u043e\u0448\u0435\u043d\u044b. \u0412\u043e\u0439\u0434\u0438\u0442\u0435 \u0437\u0430\u043d\u043e\u0432\u043e \u0438 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u0442\u0435 2FA.</gray>"));
                    }
                });
            }
            return;
        }
        if ("login_verdict".equalsIgnoreCase(type)) {
            String targetPlayer = this.extractField(rawJson, "player");
            String status = this.extractField(rawJson, "status");
            String code = this.extractField(rawJson, "code");
            String ip = this.extractField(rawJson, "ip");
            String timeoutStr = this.extractField(rawJson, "timeout");
            int timeout = 180;
            try {
                if (!timeoutStr.isEmpty()) {
                    timeout = Integer.parseInt(timeoutStr);
                }
            }
            catch (Exception p) {
                // empty catch block
            }
            int trustHours = VanillaBridge.parseTrustHours(this.extractField(rawJson, "trust_hours"), 48);
            String sessionId = this.extractField(rawJson, "session_id");
            Player p2 = Bukkit.getPlayerExact((String)targetPlayer);
            if (p2 != null && p2.isOnline()) {
                if ("require_2fa".equalsIgnoreCase(status)) {
                    if (this.securityIpManager != null) {
                        this.securityIpManager.start2FA(p2, code, ip, timeout, false, trustHours, sessionId);
                    }
                } else if ("dm_closed".equalsIgnoreCase(status)) {
                    if (this.securityIpManager != null) {
                        this.securityIpManager.start2FA(p2, code, ip, timeout, true, trustHours, sessionId);
                    }
                } else if ("trusted_session".equalsIgnoreCase(status)) {
                    if (this.securityIpManager != null) {
                        this.securityIpManager.trustIp(p2.getName(), ip, trustHours > 0 ? (long)trustHours * 3600000L : 0L);
                        String trustLabel = trustHours > 0 ? "\u043d\u0430 " + trustHours + "\u0447" : "\u0441\u0442\u0440\u043e\u0433\u0438\u0439 \u0440\u0435\u0436\u0438\u043c";
                        p2.sendMessage(MiniMessage.miniMessage().deserialize(("<gray>\u0421\u0435\u0441\u0441\u0438\u044f \u0431\u0435\u0437\u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u0438 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0430 \u0434\u043b\u044f IP <white>" + ip + "</white> (2FA \u043f\u0440\u043e\u043f\u0443\u0449\u0435\u043d\u043e " + trustLabel + ").</gray>")));
                    }
                } else if (("not_linked".equalsIgnoreCase(status) || "2fa_disabled".equalsIgnoreCase(status)) && this.securityIpManager != null) {
                    this.securityIpManager.cancel(p2.getUniqueId());
                    this.securityIpManager.clearPlayerSessions(targetPlayer);
                }
            }
            return;
        }
        if ("2fa_verified".equalsIgnoreCase(type)) {
            String targetPlayer = this.extractField(rawJson, "player");
            String sessionId = this.extractField(rawJson, "session_id");
            int trustHours = VanillaBridge.parseTrustHours(this.extractField(rawJson, "trust_hours"), 48);
            Player p = Bukkit.getPlayerExact((String)targetPlayer);
            if (p != null && p.isOnline() && this.securityIpManager != null && this.securityIpManager.isSessionMatching(p.getUniqueId(), sessionId)) {
                this.securityIpManager.completeVerification(p, false, trustHours);
            }
            return;
        }
        if ("2fa_rejected".equalsIgnoreCase(type)) {
            String targetPlayer = this.extractField(rawJson, "player");
            String sessionId = this.extractField(rawJson, "session_id");
            Player p = Bukkit.getPlayerExact((String)targetPlayer);
            if (p != null && p.isOnline() && this.securityIpManager != null && this.securityIpManager.isSessionMatching(p.getUniqueId(), sessionId)) {
                this.securityIpManager.rejectVerification(p, "\u0412\u0445\u043e\u0434 \u043e\u0442\u043a\u043b\u043e\u043d\u0451\u043d \u0432\u043b\u0430\u0434\u0435\u043b\u044c\u0446\u0435\u043c \u0430\u043a\u043a\u0430\u0443\u043d\u0442\u0430 \u0447\u0435\u0440\u0435\u0437 Discord!");
            }
            return;
        }
        if ("2fa_resend_result".equalsIgnoreCase(type)) {
            String targetPlayer = this.extractField(rawJson, "player");
            String successStr = this.extractField(rawJson, "success");
            String message = this.extractField(rawJson, "message");
            boolean success = "true".equalsIgnoreCase(successStr);
            Player p = Bukkit.getPlayerExact((String)targetPlayer);
            if (p != null && p.isOnline()) {
                if (success) {
                    p.sendMessage(MiniMessage.miniMessage().deserialize(("<dark_gray>\u2502</dark_gray> <green>\u2714 " + VanillaBridge.escapeJson(message) + "</green>")));
                    try {
                        p.playSound(p.getLocation(), Sound.ENTITY_EXPERIENCE_ORB_PICKUP, 1.0f, 1.2f);
                    }
                    catch (Exception timeout) {}
                } else {
                    p.sendMessage(MiniMessage.miniMessage().deserialize(("<dark_gray>\u2502</dark_gray> <red>\u274c " + VanillaBridge.escapeJson(message) + "</red>")));
                    try {
                        p.playSound(p.getLocation(), Sound.BLOCK_NOTE_BLOCK_BASS, 1.0f, 0.6f);
                    }
                    catch (Exception timeout) {
                        // empty catch block
                    }
                }
            }
            return;
        }
        if ("link_result".equalsIgnoreCase(type)) {
            String targetPlayer = this.extractField(rawJson, "player");
            String successStr = this.extractField(rawJson, "success");
            String message = this.extractField(rawJson, "message");
            String discordTag = this.extractField(rawJson, "discord_tag");
            String kickRelogin = this.extractField(rawJson, "kick_relogin");
            Player p = Bukkit.getPlayerExact((String)targetPlayer);
            if (p != null && p.isOnline()) {
                if ("true".equalsIgnoreCase(successStr)) {
                    p.sendMessage(MiniMessage.miniMessage().deserialize(("\n<gradient:#ff7a00:#ffae19><bold>\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501 \u2726 \u0423\u0421\u041f\u0415\u0428\u041d\u041e \u2726 \u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501</bold></gradient>\n  <green><bold>\u2714 \u0410\u043a\u043a\u0430\u0443\u043d\u0442 \u0443\u0441\u043f\u0435\u0448\u043d\u043e \u043f\u0440\u0438\u0432\u044f\u0437\u0430\u043d \u043a Discord:</bold></green> <yellow>" + discordTag + "</yellow>\n  <gray>\u0414\u0432\u0443\u0445\u0444\u0430\u043a\u0442\u043e\u0440\u043d\u0430\u044f \u0437\u0430\u0449\u0438\u0442\u0430 (2FA) \u0430\u043a\u0442\u0438\u0432\u0438\u0440\u043e\u0432\u0430\u043d\u0430.</gray>\n<gradient:#ff7a00:#ffae19><bold>\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501</bold></gradient>\n")));
                    try {
                        p.playSound(p.getLocation(), Sound.ENTITY_PLAYER_LEVELUP, 1.0f, 1.2f);
                        p.playSound(p.getLocation(), Sound.UI_TOAST_CHALLENGE_COMPLETE, 0.8f, 1.4f);
                    }
                    catch (Exception p2) {
                        // empty catch block
                    }
                    if ("true".equalsIgnoreCase(kickRelogin)) {
                        Bukkit.getScheduler().runTaskLater((Plugin)this, () -> {
                            if (p.isOnline()) {
                                p.kick(MiniMessage.miniMessage().deserialize(("<gradient:#ff7a00:#ffae19><bold>Vanilla Land</bold></gradient> <dark_gray>\u2502</dark_gray> <green>\u041f\u0440\u0438\u0432\u044f\u0437\u043a\u0430 Discord</green>\n\n<green><bold>\u2714 \u0410\u043a\u043a\u0430\u0443\u043d\u0442 \u0443\u0441\u043f\u0435\u0448\u043d\u043e \u043f\u0440\u0438\u0432\u044f\u0437\u0430\u043d!</bold></green>\n<gray>Discord: <yellow>" + MiniMessage.miniMessage().escapeTags(discordTag) + "</yellow></gray>\n\n<white>\u041f\u043e\u0436\u0430\u043b\u0443\u0439\u0441\u0442\u0430, \u043f\u0435\u0440\u0435\u0437\u0430\u0439\u0434\u0438\u0442\u0435 \u043d\u0430 \u0441\u0435\u0440\u0432\u0435\u0440 \u0434\u043b\u044f \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u0438\u044f \u0430\u0432\u0442\u043e\u0440\u0438\u0437\u0430\u0446\u0438\u0438.</white>")));
                            }
                        }, 30L);
                    }
                } else {
                    p.sendMessage(MiniMessage.miniMessage().deserialize(("<red>\u274c \u041e\u0448\u0438\u0431\u043a\u0430 \u043f\u0440\u0438\u0432\u044f\u0437\u043a\u0438: " + (message.isEmpty() ? "\u041d\u0435\u0432\u0435\u0440\u043d\u044b\u0439 \u043a\u043e\u0434" : message) + "</red>")));
                    try {
                        p.playSound(p.getLocation(), Sound.BLOCK_NOTE_BLOCK_BASS, 1.0f, 0.6f);
                    }
                    catch (Exception p2) {
                        // empty catch block
                    }
                }
            }
            return;
        }
        if ("mc_link_code_generated".equalsIgnoreCase(type)) {
            String targetPlayer = this.extractField(rawJson, "player");
            String codeStr = this.extractField(rawJson, "code");
            Player p = Bukkit.getPlayerExact((String)targetPlayer);
            if (p != null && p.isOnline()) {
                p.sendMessage(MiniMessage.miniMessage().deserialize(("\n<gradient:#ff7a00:#ffae19><bold>\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501 \u2726 \u041f\u0420\u0418\u0412\u042f\u0417\u041a\u0410 DISCORD \u2726 \u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501</bold></gradient>\n  <gray>\u0412\u0430\u0448 6-\u0437\u043d\u0430\u0447\u043d\u044b\u0439 \u043a\u043e\u0434 \u0434\u043b\u044f \u043f\u0440\u0438\u0432\u044f\u0437\u043a\u0438:</gray> <yellow><bold>" + codeStr + "</bold></yellow>\n\n  <white>\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u0432 Discord \u043a\u043e\u043c\u0430\u043d\u0434\u0443:</white> <gradient:#ff7a00:#ffae19><bold>!link " + codeStr + "</bold></gradient>\n  <gray>\u0438\u043b\u0438 \u043d\u0430\u0436\u043c\u0438\u0442\u0435 \u043a\u043d\u043e\u043f\u043a\u0443 <white>\u00ab\u041f\u0440\u0438\u0432\u044f\u0437\u0430\u0442\u044c \u0430\u043a\u043a\u0430\u0443\u043d\u0442\u00bb</white> \u0432 Discord-\u043a\u0430\u043d\u0430\u043b\u0435.</gray>\n  <dark_gray>\u0421\u0440\u043e\u043a \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u044f \u043a\u043e\u0434\u0430: 10 \u043c\u0438\u043d\u0443\u0442.</dark_gray>\n<gradient:#ff7a00:#ffae19><bold>\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501</bold></gradient>\n")));
                try {
                    p.playSound(p.getLocation(), Sound.BLOCK_NOTE_BLOCK_PLING, 1.0f, 1.2f);
                }
                catch (Exception discordTag) {
                    // empty catch block
                }
            }
            return;
        }
        if ("clear_sessions".equalsIgnoreCase(type)) {
            String targetPlayer = this.extractField(rawJson, "player");
            if (this.securityIpManager != null && !targetPlayer.isEmpty()) {
                this.securityIpManager.clearPlayerSessions(targetPlayer);
            }
            return;
        }
        if ("account_unlinked".equalsIgnoreCase(type)) {
            Player p;
            String targetPlayer = this.extractField(rawJson, "player");
            if (this.securityIpManager != null && !targetPlayer.isEmpty()) {
                this.securityIpManager.clearPlayerSessions(targetPlayer);
            }
            if ((p = Bukkit.getPlayerExact((String)targetPlayer)) != null) {
                if (this.securityIpManager != null) {
                    this.securityIpManager.cancel(p.getUniqueId());
                }
                p.sendMessage(MiniMessage.miniMessage().deserialize("<gradient:#ff7a00:#ffae19>Vanilla Land</gradient> <dark_gray>\u2502</dark_gray> <gray>\u041f\u0440\u0438\u0432\u044f\u0437\u043a\u0430 \u0430\u043a\u043a\u0430\u0443\u043d\u0442\u0430 \u043a Discord \u0430\u043d\u043d\u0443\u043b\u0438\u0440\u043e\u0432\u0430\u043d\u0430. \u0414\u0432\u0443\u0445\u0444\u0430\u043a\u0442\u043e\u0440\u043d\u0430\u044f \u0437\u0430\u0449\u0438\u0442\u0430 2FA \u043e\u0442\u043a\u043b\u044e\u0447\u0435\u043d\u0430.</gray>"));
            }
            return;
        }
        if ("scan_online_bans".equalsIgnoreCase(type)) {
            Bukkit.getScheduler().runTaskAsynchronously((Plugin)this, () -> {
                StringBuilder playersJson = new StringBuilder("[");
                boolean firstP = true;

                for (Player p : Bukkit.getOnlinePlayers()) {
                    String pName = p.getName();
                    String ip = "127.0.0.1";
                    if (p.getAddress() != null && p.getAddress().getAddress() != null) {
                        ip = p.getAddress().getAddress().getHostAddress();
                    }

                    // Query LiteBans {history} by exact IP to get past accounts
                    Set<String> alts = new java.util.LinkedHashSet<>();
                    if (!ip.equals("127.0.0.1") && !ip.equals("localhost")) {
                        try {
                            Class<?> dbClass = Class.forName("litebans.api.Database");
                            Method get = dbClass.getMethod("get");
                            Object db = get.invoke(null);
                            if (db != null) {
                                Method executeQuery = dbClass.getMethod("executeQuery", String.class, Object[].class);
                                String hSql = "SELECT name FROM {history} WHERE ip=? ORDER BY date DESC LIMIT 40";
                                Object rsObj = executeQuery.invoke(db, hSql, new Object[]{ip});
                                if (rsObj instanceof ResultSet) {
                                    try (ResultSet rs = (ResultSet) rsObj) {
                                        while (rs.next()) {
                                            String an = rs.getString("name");
                                            if (an != null && !an.trim().isEmpty() && !an.equalsIgnoreCase(pName)) {
                                                alts.add(an.trim());
                                            }
                                        }
                                    }
                                }
                            }
                        } catch (Throwable ignored) {}
                    }

                    StringBuilder bannedArr = new StringBuilder("[");
                    StringBuilder cleanArr = new StringBuilder("[");
                    boolean firstB = true;
                    boolean firstC = true;

                    for (String alt : alts) {
                        Map<String, String> bInfo = VanillaBridge.queryLiteBansBan(alt, null, ip);
                        if (bInfo != null) {
                            if (!firstB) bannedArr.append(",");
                            bannedArr.append("{\"player\":\"").append(VanillaBridge.escapeJson(alt))
                                     .append("\",\"reason\":\"").append(VanillaBridge.escapeJson(bInfo.getOrDefault("reason", "Нарушение правил")))
                                     .append("\",\"duration\":\"").append(VanillaBridge.escapeJson(bInfo.getOrDefault("duration", "Навсегда")))
                                     .append("\",\"banned_by\":\"").append(VanillaBridge.escapeJson(bInfo.getOrDefault("banned_by", "Console")))
                                     .append("\"}");
                            firstB = false;
                        } else {
                            if (!firstC) cleanArr.append(",");
                            cleanArr.append("\"").append(VanillaBridge.escapeJson(alt)).append("\"");
                            firstC = false;
                        }
                    }
                    bannedArr.append("]");
                    cleanArr.append("]");

                    if (alts.size() > 0) {
                        if (!firstP) playersJson.append(",");
                        playersJson.append("{\"player\":\"").append(VanillaBridge.escapeJson(pName))
                                   .append("\",\"ip\":\"").append(VanillaBridge.escapeJson(ip))
                                   .append("\",\"banned_alts\":").append(bannedArr.toString())
                                   .append(",\"clean_alts\":").append(cleanArr.toString())
                                   .append("}");
                        firstP = false;
                    }
                }
                playersJson.append("]");

                String resp = "{\"type\":\"scan_online_bans_result\",\"total_online\":" + Bukkit.getOnlinePlayers().size() + ",\"players\":" + playersJson.toString() + "}";
                if (this.bridgeClient != null && this.bridgeClient.isConnected()) {
                    this.bridgeClient.send(resp);
                }
            });
            return;
        }
        if ("check_alts_bans".equalsIgnoreCase(type)) {
            String loginPlayer = this.extractField(rawJson, "player");
            String ip = this.extractField(rawJson, "ip");
            String altsStr = this.extractField(rawJson, "alts");
            Bukkit.getScheduler().runTaskAsynchronously((Plugin)this, () -> {
                Map<String, UUID> candidates = new LinkedHashMap<>();
                if (loginPlayer != null && !loginPlayer.trim().isEmpty()) {
                    OfflinePlayer lop = Bukkit.getOfflinePlayer(loginPlayer.trim());
                    candidates.put(loginPlayer.trim(), lop != null ? lop.getUniqueId() : null);
                }
                if (altsStr != null && !altsStr.trim().isEmpty()) {
                    for (String a : altsStr.split(",")) {
                        a = a.trim();
                        if (!a.isEmpty()) {
                            boolean exists = false;
                            for (String k : candidates.keySet()) {
                                if (k.equalsIgnoreCase(a)) { exists = true; break; }
                            }
                            if (!exists) {
                                OfflinePlayer aop = Bukkit.getOfflinePlayer(a);
                                candidates.put(a, aop != null ? aop.getUniqueId() : null);
                            }
                        }
                    }
                }

                // Query LiteBans {history} by exact IP to get ALL past accounts and their LiteBans UUIDs!
                if (ip != null && !ip.isEmpty() && !ip.equals("127.0.0.1") && !ip.equals("localhost")) {
                    try {
                        Class<?> dbClass = Class.forName("litebans.api.Database");
                        Method get = dbClass.getMethod("get");
                        Object db = get.invoke(null);
                        if (db != null) {
                            Method executeQuery = dbClass.getMethod("executeQuery", String.class, Object[].class);
                            String histSql = "SELECT name, uuid FROM {history} WHERE ip=? ORDER BY date DESC LIMIT 50";
                            Object rsObj = executeQuery.invoke(db, histSql, new Object[]{ip});
                            if (rsObj instanceof ResultSet) {
                                try (ResultSet rs = (ResultSet) rsObj) {
                                    while (rs.next()) {
                                        String hName = rs.getString("name");
                                        String hUuidStr = rs.getString("uuid");
                                        if (hName != null && !hName.trim().isEmpty()) {
                                            String cleanName = hName.trim();
                                            UUID u = null;
                                            if (hUuidStr != null && !hUuidStr.trim().isEmpty()) {
                                                try { u = UUID.fromString(hUuidStr.trim()); } catch (Exception ignored) {}
                                            }
                                            if (u == null) {
                                                OfflinePlayer hop = Bukkit.getOfflinePlayer(cleanName);
                                                u = hop != null ? hop.getUniqueId() : null;
                                            }

                                            String existingKey = null;
                                            for (String k : candidates.keySet()) {
                                                if (k.equalsIgnoreCase(cleanName)) {
                                                    existingKey = k;
                                                    break;
                                                }
                                            }
                                            if (existingKey != null) {
                                                if (u != null) {
                                                    candidates.put(existingKey, u);
                                                }
                                            } else {
                                                candidates.put(cleanName, u);
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    } catch (Throwable t) {
                        this.getLogger().warning("[VanillaBridge] Ошибка запроса {history} LiteBans: " + t.getMessage());
                    }
                }

                this.getLogger().info("[VanillaBridge Security] Проверка твинков для " + loginPlayer + " (IP: " + ip + ", аккаунты: " + candidates.keySet() + ")");

                StringBuilder bannedJson = new StringBuilder("[");
                StringBuilder cleanJson = new StringBuilder("[");
                boolean firstBanned = true;
                boolean firstClean = true;
                int bannedCount = 0;
                int cleanCount = 0;

                for (Map.Entry<String, UUID> entry : candidates.entrySet()) {
                    String alt = entry.getKey();
                    UUID altUuid = entry.getValue();
                    Map<String, String> banInfo = VanillaBridge.queryLiteBansBan(alt, altUuid, ip);
                    boolean isOnline = Bukkit.getPlayerExact(alt) != null;
                    if (banInfo != null) {
                        bannedCount++;
                        this.getLogger().warning("[VanillaBridge Security] -> ОБНАРУЖЕН БАН в LiteBans для " + alt + " (причина: " + banInfo.get("reason") + ", выдал: " + banInfo.get("banned_by") + ")");
                        if (!firstBanned) {
                            bannedJson.append(",");
                        }
                        bannedJson.append("{\"player\":\"").append(VanillaBridge.escapeJson(alt))
                                  .append("\",\"reason\":\"").append(VanillaBridge.escapeJson(banInfo.getOrDefault("reason", "\u041d\u0430\u0440\u0443\u0448\u0435\u043d\u0438\u0435 \u043f\u0440\u0430\u0432\u0438\u043b")))
                                  .append("\",\"duration\":\"").append(VanillaBridge.escapeJson(banInfo.getOrDefault("duration", "\u041d\u0430\u0440\u0443\u0448\u0435\u043d\u0438\u0435 \u043f\u0440\u0430\u0432\u0438\u043b")))
                                  .append("\",\"banned_by\":\"").append(VanillaBridge.escapeJson(banInfo.getOrDefault("banned_by", "Console")))
                                  .append("\",\"is_ip_ban\":").append("true".equals(banInfo.get("is_ip_ban")))
                                  .append(",\"online\":").append(isOnline)
                                  .append("}");
                        firstBanned = false;
                    } else {
                        cleanCount++;
                        if (!firstClean) {
                            cleanJson.append(",");
                        }
                        cleanJson.append("{\"player\":\"").append(VanillaBridge.escapeJson(alt))
                                 .append("\",\"online\":").append(isOnline)
                                 .append("}");
                        firstClean = false;
                    }
                }
                bannedJson.append("]");
                cleanJson.append("]");

                String resp = "{\"type\":\"alts_bans_result\",\"player\":\"" + VanillaBridge.escapeJson(loginPlayer)
                            + "\",\"ip\":\"" + VanillaBridge.escapeJson(ip)
                            + "\",\"banned\":" + bannedJson.toString()
                            + ",\"clean\":" + cleanJson.toString() + "}";

                this.getLogger().info("[VanillaBridge Security] Отправлен результат боту для " + loginPlayer + ": забанено=" + bannedCount + ", чистых=" + cleanCount);
                if (this.bridgeClient != null && this.bridgeClient.isConnected()) {
                    this.bridgeClient.send(resp);
                }
            });
            return;
        }
        if ("execute_console_command".equalsIgnoreCase(type)) {
            String cmdToRun = this.extractField(rawJson, "command");
            if (!cmdToRun.isEmpty()) {
                Bukkit.getScheduler().runTask((Plugin)this, () -> Bukkit.dispatchCommand((CommandSender)Bukkit.getConsoleSender(), (String)cmdToRun));
            }
            return;
        }
        if (!"discord_chat".equalsIgnoreCase(type)) {
            return;
        }
        String author = this.extractField(rawJson, "author");
        String content = this.extractField(rawJson, "content");
        if (author.isEmpty() || content.isEmpty()) {
            return;
        }
        boolean useIcon = this.getConfig().getBoolean("discord-format.use-icon", true);
        String icon = useIcon ? this.getConfig().getString("discord-format.icon", "\u0152") : "";
        String iconPart = useIcon && !icon.isEmpty() ? icon + " " : "";
        String safeAuthor = MiniMessage.miniMessage().escapeTags(author);
        String badgeGrad = this.getConfig().getString("discord-format.badge-gradient", "<gradient:#5865F2:#7289DA>");
        if (!badgeGrad.startsWith("<") && badgeGrad.startsWith("#")) {
            badgeGrad = "<color:" + badgeGrad + ">";
        }
        String closeGrad = badgeGrad.contains("gradient") ? "</gradient>" : (badgeGrad.contains("color") ? "</color>" : "");
        String prefixMini = badgeGrad + iconPart + "Discord" + closeGrad + " <dark_gray>|</dark_gray> <white>" + safeAuthor + "</white><dark_gray>:</dark_gray> ";
        try {
            prefixComponent = MiniMessage.miniMessage().deserialize(prefixMini);
        }
        catch (Exception e) {
            prefixComponent = Component.text((String)((useIcon ? "\u0152 " : "") + "Discord | " + author + ": "));
        }
        String hoverText = this.getConfig().getString("discord-format.hover-text", "&7\u0421\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435 \u0438\u0437 Discord\n&e\u041a\u043b\u0438\u043a: \u043e\u0442\u0432\u0435\u0442\u0438\u0442\u044c");
        TextComponent hoverComponent = LegacyComponentSerializer.legacyAmpersand().deserialize(hoverText);
        prefixComponent = prefixComponent.hoverEvent((HoverEventSource)HoverEvent.showText((Component)hoverComponent)).clickEvent(ClickEvent.suggestCommand((String)("@" + author + " ")));
        Component messageBody = VanillaBridge.parseUrlsInComponent(content);
        Component fullMessage = prefixComponent.append(messageBody);
        boolean mentionsEnabled = this.getConfig().getBoolean("mentions.enabled", true);
        String soundName = this.getConfig().getString("mentions.sound.name", "block.note_block.pling");
        float soundVolume = (float)this.getConfig().getDouble("mentions.sound.volume", 1.0);
        float soundPitch = (float)this.getConfig().getDouble("mentions.sound.pitch", 1.5);
        Bukkit.getScheduler().runTask((Plugin)this, () -> {
            for (Player p : Bukkit.getOnlinePlayers()) {
                p.sendMessage(fullMessage);
                if (!mentionsEnabled || !content.toLowerCase().contains("@" + p.getName().toLowerCase())) continue;
                try {
                    Sound sound = Sound.valueOf((String)soundName.toUpperCase().replace('.', '_'));
                    p.playSound(p.getLocation(), sound, soundVolume, soundPitch);
                }
                catch (Exception ignored) {
                    p.playSound(p.getLocation(), Sound.BLOCK_NOTE_BLOCK_PLING, soundVolume, soundPitch);
                }
            }
            Bukkit.getConsoleSender().sendMessage(fullMessage);
        });
    }

    public void handlePostLoginCheck(Player player) {
        if (!this.twoFactorEnabled) {
            return;
        }
        if (player == null || !player.isOnline()) {
            return;
        }
        String ip = "127.0.0.1";
        if (player.getAddress() != null && player.getAddress().getAddress() != null) {
            ip = player.getAddress().getAddress().getHostAddress();
        }
        if (this.bridgeClient != null && this.bridgeClient.isConnected()) {
            String payload = String.format(Locale.US, "{\"type\":\"check_login\",\"player\":\"%s\",\"uuid\":\"%s\",\"ip\":\"%s\"}", VanillaBridge.escapeJson(player.getName()), player.getUniqueId().toString(), VanillaBridge.escapeJson(ip));
            this.bridgeClient.send(payload);
        } else if (this.securityIpManager != null && this.securityIpManager.isIpTrusted(player.getName(), ip)) {
            int cachedHours = this.securityIpManager.getTrustHoursFor(player.getName(), ip);
            String trustLabel = cachedHours > 0 ? "\u043d\u0430 " + cachedHours + "\u0447" : "\u0441\u0442\u0440\u043e\u0433\u0438\u0439 \u0440\u0435\u0436\u0438\u043c";
            player.sendMessage(MiniMessage.miniMessage().deserialize(("<gray>\u0421\u0435\u0441\u0441\u0438\u044f \u0431\u0435\u0437\u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u0438 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0430 \u0434\u043b\u044f IP <white>" + ip + "</white> (2FA \u043f\u0440\u043e\u043f\u0443\u0449\u0435\u043d\u043e " + trustLabel + ").</gray>")));
        }
    }

    private static int parseTrustHours(String raw, int fallback) {
        if (raw == null || raw.trim().isEmpty()) {
            return fallback;
        }
        try {
            return (int)Math.round(Double.parseDouble(raw.trim()));
        }
        catch (NumberFormatException ignored) {
            return fallback;
        }
    }

    public SecurityIpManager getSecurityIpManager() {
        return this.securityIpManager;
    }

    public AuthMeHook getAuthMeHook() {
        return this.authMeHook;
    }

    public static String stripMinecraftColors(String input) {
        if (input == null || input.isEmpty()) return "";
        return input.replaceAll("(?i)[&§][0-9a-fk-or]", "").trim();
    }

    public static Map<String, String> queryLiteBansBan(String playerName) {
        OfflinePlayer op = Bukkit.getOfflinePlayer(playerName);
        return queryLiteBansBan(playerName, op != null ? op.getUniqueId() : null, null);
    }

    public static Map<String, String> queryLiteBansBan(String playerName, UUID uuid, String ip) {
        try {
            Class<?> dbClass = Class.forName("litebans.api.Database");
            Method get = dbClass.getMethod("get");
            Object db = get.invoke(null);
            if (db == null) return null;

            Method executeQuery = dbClass.getMethod("executeQuery", String.class, Object[].class);

            UUID litebansUuid = uuid;
            if (playerName != null && !playerName.trim().isEmpty()) {
                try {
                    String hSql = "SELECT uuid FROM {history} WHERE lower(name)=lower(?) ORDER BY date DESC LIMIT 1";
                    Object rsH = executeQuery.invoke(db, hSql, new Object[]{playerName.trim()});
                    if (rsH instanceof ResultSet) {
                        try (ResultSet r = (ResultSet) rsH) {
                            if (r.next()) {
                                String uStr = r.getString("uuid");
                                if (uStr != null && !uStr.trim().isEmpty()) {
                                    try { litebansUuid = UUID.fromString(uStr.trim()); } catch (Exception ignored) {}
                                }
                            }
                        }
                    }
                } catch (Throwable ignored) {}
            }

            if (litebansUuid == null && playerName != null && !playerName.isEmpty()) {
                OfflinePlayer op = Bukkit.getOfflinePlayer(playerName);
                if (op != null) {
                    litebansUuid = op.getUniqueId();
                }
            }

            long now = System.currentTimeMillis();
            String u1 = litebansUuid != null ? litebansUuid.toString() : "";
            String u1NoDash = litebansUuid != null ? litebansUuid.toString().replace("-", "") : "";
            String u2 = uuid != null ? uuid.toString() : "";
            String u2NoDash = uuid != null ? uuid.toString().replace("-", "") : "";
            String pName = playerName != null ? playerName.trim() : "";
            String cleanIp = (ip != null && !ip.trim().isEmpty() && !ip.equals("127.0.0.1") && !ip.equals("localhost")) ? ip.trim() : "";

            // 1. Direct query in LiteBans {bans} table (clean schema without non-existent 'permanent' column!)
            try {
                String banSql = "SELECT reason, until, banned_by_name, ipban FROM {bans} WHERE active=1 "
                              + "AND (until <= 0 OR until > " + now + ") AND ("
                              + "(uuid IS NOT NULL AND (uuid=? OR uuid=? OR uuid=? OR uuid=?)) OR "
                              + "uuid IN (SELECT uuid FROM {history} WHERE lower(name)=lower(?))"
                              + (cleanIp.isEmpty() ? "" : " OR (ip IS NOT NULL AND ip=?)")
                              + ") ORDER BY id DESC LIMIT 1";

                Object[] params = cleanIp.isEmpty()
                    ? new Object[]{u1, u1NoDash, u2, u2NoDash, pName}
                    : new Object[]{u1, u1NoDash, u2, u2NoDash, pName, cleanIp};

                Object rsObj = executeQuery.invoke(db, banSql, params);
                if (rsObj instanceof ResultSet) {
                    try (ResultSet r = (ResultSet) rsObj) {
                        if (r.next()) {
                            String rawReason = r.getString("reason");
                            long until = r.getLong("until");
                            String by = r.getString("banned_by_name");
                            boolean isIpBan = false;
                            try { isIpBan = r.getBoolean("ipban"); } catch (Exception ignored) {}

                            Map<String, String> res = new HashMap<>();
                            res.put("banned", "true");
                            String cleanReason = stripMinecraftColors(rawReason);
                            res.put("reason", !cleanReason.isEmpty() ? cleanReason : "\u041d\u0430\u0440\u0443\u0448\u0435\u043d\u0438\u0435 \u043f\u0440\u0430\u0432\u0438\u043b");
                            res.put("banned_by", (by != null && !by.trim().isEmpty()) ? by.trim() : "Console");
                            res.put("is_ip_ban", isIpBan ? "true" : "false");

                            if (until > 0L) {
                                long diffSec = (until - now) / 1000L;
                                if (diffSec > 0) {
                                    if (diffSec > 86400L) {
                                        res.put("duration", (diffSec / 86400L) + " \u0434\u043d.");
                                    } else if (diffSec > 3600L) {
                                        res.put("duration", (diffSec / 3600L) + " \u0447.");
                                    } else {
                                        res.put("duration", Math.max(1L, diffSec / 60L) + " \u043c\u0438\u043d.");
                                    }
                                } else {
                                    return null; // Ban expired
                                }
                            } else {
                                res.put("duration", "\u041d\u0430\u0432\u0441\u0435\u0433\u0434\u0430");
                            }
                            return res;
                        }
                    }
                }
            } catch (Throwable sqlEx) {
                Bukkit.getLogger().warning("[VanillaBridge Security] Direct bans SQL query error: " + sqlEx.getMessage());
            }

            // 2. Fallback to native isPlayerBanned method
            try {
                Method isPlayerBannedMethod = dbClass.getMethod("isPlayerBanned", UUID.class, String.class);
                boolean bannedNative = false;
                if (litebansUuid != null) {
                    Boolean b = (Boolean) isPlayerBannedMethod.invoke(db, litebansUuid, cleanIp.isEmpty() ? null : cleanIp);
                    if (b != null && b.booleanValue()) bannedNative = true;
                }
                if (!bannedNative && uuid != null && !uuid.equals(litebansUuid)) {
                    Boolean b = (Boolean) isPlayerBannedMethod.invoke(db, uuid, cleanIp.isEmpty() ? null : cleanIp);
                    if (b != null && b.booleanValue()) bannedNative = true;
                }
                if (bannedNative) {
                    Map<String, String> res = new HashMap<>();
                    res.put("banned", "true");
                    res.put("reason", "\u041d\u0430\u0440\u0443\u0448\u0435\u043d\u0438\u0435 \u043f\u0440\u0430\u0432\u0438\u043b");
                    res.put("duration", "\u041d\u0430\u0432\u0441\u0435\u0433\u0434\u0430");
                    res.put("banned_by", "Console");
                    res.put("is_ip_ban", "false");
                    return res;
                }
            } catch (Throwable ignored) {}

            return null;
        } catch (Throwable t) {
            Bukkit.getLogger().warning("[VanillaBridge] Error in queryLiteBansBan for " + playerName + ": " + t.getMessage());
            return null;
        }
    }

    private String extractField(String json, String field) {
        if (json == null || json.isEmpty()) {
            return "";
        }
        try {
            JsonObject obj;
            JsonElement el = JsonParser.parseString((String)json);
            if (el.isJsonObject() && (obj = el.getAsJsonObject()).has(field) && !obj.get(field).isJsonNull()) {
                return obj.get(field).getAsString();
            }
        }
        catch (Throwable el) {
            // empty catch block
        }
        Matcher m = JSON_EXTRACT_PATTERN.matcher(json);
        while (m.find()) {
            if (!field.equals(m.group(1))) continue;
            if (m.group(2) != null) {
                return this.unescapeJson(m.group(2));
            }
            if (m.group(3) == null) continue;
            return m.group(3);
        }
        return "";
    }

    private String unescapeJson(String input) {
        return input.replace("\\\"", "\"").replace("\\\\", "\\").replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t");
    }

    public static String escapeJson(String text) {
        if (text == null) {
            return "";
        }
        return text.replace("\\", "\\\\").replace("\"", "\\\"").replace("\b", "\\b").replace("\f", "\\f").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t");
    }

    public static int getSafeMineStat(OfflinePlayer player, Material material) {
        if (player == null || material == null) {
            return 0;
        }
        try {
            return player.getStatistic(Statistic.MINE_BLOCK, material);
        }
        catch (Throwable ignored) {
            return 0;
        }
    }

    public void broadcastAnnouncement(String text, String authorName) {
        this.broadcastAnnouncement(text, authorName, true);
    }

    public void broadcastAnnouncement(String text, String authorName, boolean sendToDiscord) {
        if (text == null || text.trim().isEmpty()) {
            return;
        }
        if (!Bukkit.isPrimaryThread()) {
            Bukkit.getScheduler().runTask((Plugin)this, () -> this.broadcastAnnouncement(text, authorName, sendToDiscord));
            return;
        }
        Component comp = VanillaBridge.parseFormattedText(text);
        String authorSuffix = authorName != null && !authorName.isEmpty() && !authorName.equalsIgnoreCase("\u0421\u0435\u0440\u0432\u0435\u0440") && !authorName.equalsIgnoreCase("Discord") ? " <dark_gray>[" + MiniMessage.miniMessage().escapeTags(authorName) + "]</dark_gray>" : "";
        Component topBorder = MiniMessage.miniMessage().deserialize(("\n<gradient:#FFA500:#FF7700>\u2726 \u2500\u2500 \ud83d\udce2 \u041e\u0411\u042a\u042f\u0412\u041b\u0415\u041d\u0418\u0415 \u0421\u0415\u0420\u0412\u0415\u0420\u0410 \u2500\u2500 \u2726</gradient>" + authorSuffix + "\n"));
        Component bottomBorder = MiniMessage.miniMessage().deserialize("\n<gradient:#FFA500:#FF7700>\u2726 \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 \u2726</gradient>\n");
        Component fullBanner = topBorder.append((Component)Component.text((String)"  ")).append(comp).append(bottomBorder);
        for (Player pl : Bukkit.getOnlinePlayers()) {
            pl.sendMessage(fullBanner);
            pl.sendActionBar(MiniMessage.miniMessage().deserialize("<gradient:#FFA500:#FF7700>\ud83d\udce2 <bold>\u0412\u0430\u0436\u043d\u043e\u0435 \u043e\u0431\u044a\u044f\u0432\u043b\u0435\u043d\u0438\u0435 \u0432 \u0447\u0430\u0442\u0435!</bold></gradient>"));
            try {
                pl.playSound(pl.getLocation(), Sound.BLOCK_NOTE_BLOCK_BELL, 1.0f, 1.0f);
                pl.playSound(pl.getLocation(), Sound.BLOCK_NOTE_BLOCK_CHIME, 1.0f, 1.2f);
            }
            catch (Exception exception) {}
        }
        Bukkit.getConsoleSender().sendMessage(fullBanner);
        if (sendToDiscord && this.bridgeClient != null && this.bridgeClient.isConnected()) {
            String payload = String.format(Locale.US, "{\"type\":\"mc_broadcast\",\"author\":\"%s\",\"text\":\"%s\"}", VanillaBridge.escapeJson(authorName != null ? authorName : "\u0421\u0435\u0440\u0432\u0435\u0440"), VanillaBridge.escapeJson(text));
            this.bridgeClient.send(payload);
        }
    }

    public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (!sender.hasPermission("vanillabridge.admin")) {
            sender.sendMessage("\u00a7c\u0423 \u0432\u0430\u0441 \u043d\u0435\u0442 \u043f\u0440\u0430\u0432 \u0434\u043b\u044f \u044d\u0442\u043e\u0439 \u043a\u043e\u043c\u0430\u043d\u0434\u044b!");
            return true;
        }
        if (args.length > 0 && args[0].equalsIgnoreCase("2fa")) {
            if (args.length > 1) {
                String sub = args[1].toLowerCase();
                if (sub.equals("off") || sub.equals("disable") || sub.equals("false")) {
                    this.twoFactorEnabled = false;
                    this.getConfig().set("security.two-factor.enabled", false);
                    this.saveConfig();
                    sender.sendMessage("§6[VanillaBridge] §cДвухфакторная защита 2FA отключена на этом сервере.");
                    return true;
                }
                if (sub.equals("on") || sub.equals("enable") || sub.equals("true")) {
                    this.twoFactorEnabled = true;
                    this.getConfig().set("security.two-factor.enabled", true);
                    this.saveConfig();
                    sender.sendMessage("§6[VanillaBridge] §aДвухфакторная защита 2FA включена на этом сервере.");
                    return true;
                }
            }
            String stateStr = this.twoFactorEnabled ? "§aВКЛЮЧЕНА" : "§cОТКЛЮЧЕНА";
            String sId = this.getConfig().getString("server-id", "main");
            sender.sendMessage("§6[VanillaBridge] §f2FA статус: " + stateStr + " §7(Сервер: §e" + sId + "§7)");
            sender.sendMessage("§7Использование: §f/bridge 2fa <on|off>");
            return true;
        }
        if (args.length > 0 && args[0].equalsIgnoreCase("test")) {
            if (this.bridgeClient != null) {
                this.bridgeClient.runDiagnostic(sender);
            } else {
                sender.sendMessage("\u00a7c[VanillaBridge] bridgeClient \u043d\u0435 \u0438\u043d\u0438\u0446\u0438\u0430\u043b\u0438\u0437\u0438\u0440\u043e\u0432\u0430\u043d!");
            }
            return true;
        }
        if (args.length > 0 && args[0].equalsIgnoreCase("reload")) {
            this.migrateConfig();
            if (this.bridgeClient != null) {
                this.bridgeClient.disconnect();
                this.bridgeClient.connect();
            }
            sender.sendMessage("\u00a7a[VanillaBridge] \u041a\u043e\u043d\u0444\u0438\u0433\u0443\u0440\u0430\u0446\u0438\u044f \u043f\u0440\u043e\u0432\u0435\u0440\u0435\u043d\u0430, \u0430\u043a\u0442\u0443\u0430\u043b\u0438\u0437\u0438\u0440\u043e\u0432\u0430\u043d\u0430 \u0438 \u043c\u043e\u0441\u0442 \u043f\u0435\u0440\u0435\u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d!");
            return true;
        }
        boolean connected = this.bridgeClient != null && this.bridgeClient.isConnected();
        String status = connected ? "\u00a7a\u041f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d \u043a \u0431\u043e\u0442\u0443" : "\u00a7c\u041e\u0442\u043a\u043b\u044e\u0447\u0435\u043d \u043e\u0442 \u0431\u043e\u0442\u0430";
        sender.sendMessage("\u00a76[VanillaBridge] \u00a7f\u0421\u0442\u0430\u0442\u0443\u0441 \u043c\u043e\u0441\u0442\u0430: " + status);
        sender.sendMessage("\u00a77URL: " + this.getConfig().getString("bridge.ws-url"));
        sender.sendMessage("\u00a7e\u041a\u043e\u043c\u0430\u043d\u0434\u044b \u0434\u0438\u0430\u0433\u043d\u043e\u0441\u0442\u0438\u043a\u0438 \u0438 \u0443\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u044f:");
        sender.sendMessage("\u00a7f  /bridge test \u00a77\u2014 \u041f\u043e\u043b\u043d\u0430\u044f \u0434\u0438\u0430\u0433\u043d\u043e\u0441\u0442\u0438\u043a\u0430 \u0441\u0435\u0442\u0438 (DNS, Cloudflare WSS, HTTP /health)");
        sender.sendMessage("\u00a7f  /bridge reload \u00a77\u2014 \u0410\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u043e\u0435 \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u0435 \u043f\u0430\u0440\u0430\u043c\u0435\u0442\u0440\u043e\u0432 config.yml \u0438 \u0440\u0435\u043a\u043e\u043d\u043d\u0435\u043a\u0442");
        return true;
    }

    private String serializeItemStack(ItemStack item, int slot) {
        BlockStateMeta bsm;
        BlockState blockState;
        ItemMeta meta;
        if (item == null || item.getType().isAir()) {
            return null;
        }
        String itemType = item.getType().name();
        int count = item.getAmount();
        StringBuilder shulkerJson = new StringBuilder();
        if (itemType.contains("SHULKER_BOX") && item.hasItemMeta() && (meta = item.getItemMeta()) instanceof BlockStateMeta && (blockState = (bsm = (BlockStateMeta)meta).getBlockState()) instanceof ShulkerBox) {
            ShulkerBox shulker = (ShulkerBox)blockState;
            shulkerJson.append(",\"shulker_items\":[");
            boolean firstSh = true;
            ItemStack[] shContents = shulker.getInventory().getContents();
            for (int sSlot = 0; sSlot < shContents.length; ++sSlot) {
                ItemStack sItem = shContents[sSlot];
                if (sItem == null || sItem.getType().isAir()) continue;
                if (!firstSh) {
                    shulkerJson.append(",");
                }
                shulkerJson.append(String.format(Locale.US, "{\"slot\":%d,\"item\":\"%s\",\"count\":%d}", sSlot, sItem.getType().name(), sItem.getAmount()));
                firstSh = false;
            }
            shulkerJson.append("]");
        }
        return String.format(Locale.US, "{\"slot\":%d,\"item\":\"%s\",\"count\":%d%s}", slot, itemType, count, shulkerJson.toString());
    }

    public static Component parseUrlsInComponent(String content) {
        if (content == null || content.isEmpty()) {
            return Component.empty();
        }
        Matcher matcher = URL_PATTERN.matcher(content);
        if (!matcher.find()) {
            return Component.text((String)content, (TextColor)NamedTextColor.WHITE);
        }
        matcher.reset();
        TextComponent.Builder builder = Component.text();
        int lastEnd = 0;
        while (matcher.find()) {
            String url;
            int start = matcher.start();
            int end = matcher.end();
            if (start > lastEnd) {
                builder.append((Component)Component.text((String)content.substring(lastEnd, start), (TextColor)NamedTextColor.WHITE));
            }
            Object clickTarget = (url = matcher.group()).startsWith("http") ? url : "https://" + url;
            builder.append(((TextComponent)((TextComponent)Component.text((String)url, (TextColor)NamedTextColor.AQUA).decorate(TextDecoration.UNDERLINED)).hoverEvent((HoverEventSource)HoverEvent.showText((Component)Component.text((String)("\u00a7e\u041a\u043b\u0438\u043a: \u043f\u0435\u0440\u0435\u0439\u0442\u0438 \u043f\u043e \u0441\u0441\u044b\u043b\u043a\u0435\n\u00a77" + (String)clickTarget))))).clickEvent(ClickEvent.openUrl((String)clickTarget)));
            lastEnd = end;
        }
        if (lastEnd < content.length()) {
            builder.append((Component)Component.text((String)content.substring(lastEnd), (TextColor)NamedTextColor.WHITE));
        }
        return builder.build();
    }

    public Component buildDonateComponent() {
        return LinkComponents.buildDonateComponent();
    }

    public Component buildDiscordComponent() {
        return LinkComponents.buildDiscordComponent();
    }

    public Component buildSiteComponent() {
        return LinkComponents.buildSiteComponent();
    }

    public Component buildTelegramComponent() {
        return LinkComponents.buildTelegramComponent();
    }

    public Component buildLinksComponent() {
        return LinkComponents.buildLinksComponent();
    }

    public synchronized void updateTopCache() {
        try {
            String jsonTemplate;
            class StatEntry {
                final String name;
                final long value;
                final String skin;

                StatEntry(VanillaBridge this$0, String name, long value, String skin) {
                    this.name = name;
                    this.value = value;
                    this.skin = skin;
                }
            }
            ArrayList<StatEntry> playtimeList = new ArrayList<StatEntry>();
            ArrayList<StatEntry> diamondList = new ArrayList<StatEntry>();
            ArrayList<StatEntry> debrisList = new ArrayList<StatEntry>();
            ArrayList<StatEntry> killList = new ArrayList<StatEntry>();
            ArrayList<StatEntry> deathList = new ArrayList<StatEntry>();
            for (OfflinePlayer op : Bukkit.getOfflinePlayers()) {
                Player onlineP;
                String name = op.getName();
                if (name == null || name.isEmpty()) continue;
                int pt = 0;
                int dia = 0;
                int deb = 0;
                int kills = 0;
                int deaths = 0;
                try {
                    pt = op.getStatistic(Statistic.PLAY_ONE_MINUTE);
                    dia = op.getStatistic(Statistic.MINE_BLOCK, Material.DIAMOND_ORE) + op.getStatistic(Statistic.MINE_BLOCK, Material.DEEPSLATE_DIAMOND_ORE);
                    deb = op.getStatistic(Statistic.MINE_BLOCK, Material.ANCIENT_DEBRIS);
                    kills = op.getStatistic(Statistic.PLAYER_KILLS);
                    deaths = op.getStatistic(Statistic.DEATHS);
                }
                catch (Throwable throwable) {
                    // empty catch block
                }
                String skin = this.getCachedPlayerSkin(name);
                if (skin.isEmpty() && op.isOnline() && (onlineP = op.getPlayer()) != null && !(skin = VanillaBridge.extractSkinHash(onlineP.getPlayerProfile())).isEmpty()) {
                    this.cachePlayerSkin(name, skin);
                }
                if (pt > 0) {
                    playtimeList.add(new StatEntry(this, name, pt, skin));
                }
                if (dia > 0) {
                    diamondList.add(new StatEntry(this, name, dia, skin));
                }
                if (deb > 0) {
                    debrisList.add(new StatEntry(this, name, deb, skin));
                }
                if (kills > 0) {
                    killList.add(new StatEntry(this, name, kills, skin));
                }
                if (deaths <= 0) continue;
                deathList.add(new StatEntry(this, name, deaths, skin));
            }
            playtimeList.sort((a, b) -> Long.compare(b.value, a.value));
            diamondList.sort((a, b) -> Long.compare(b.value, a.value));
            debrisList.sort((a, b) -> Long.compare(b.value, a.value));
            killList.sort((a, b) -> Long.compare(b.value, a.value));
            deathList.sort((a, b) -> Long.compare(b.value, a.value));
            Function<List, String> listToJson = list -> {
                StringBuilder sb = new StringBuilder("[");
                int limit = Math.min(10, list.size());
                for (int i = 0; i < limit; ++i) {
                    StatEntry e = (StatEntry)list.get(i);
                    if (i > 0) {
                        sb.append(",");
                    }
                    sb.append(String.format(Locale.US, "{\"player\":\"%s\",\"value\":%d,\"skin\":\"%s\"}", VanillaBridge.escapeJson(e.name), e.value, VanillaBridge.escapeJson(e.skin)));
                }
                sb.append("]");
                return sb.toString();
            };
            this.cachedTopJson = jsonTemplate = String.format(Locale.US, "{\"type\":\"top_data\",\"query_id\":\"%%QUERY_ID%%\",\"playtime\":%s,\"diamonds\":%s,\"debris\":%s,\"kills\":%s,\"deaths\":%s}", listToJson.apply(playtimeList), listToJson.apply(diamondList), listToJson.apply(debrisList), listToJson.apply(killList), listToJson.apply(deathList));
            this.lastTopCacheTime = System.currentTimeMillis();
        }
        catch (Throwable t) {
            this.getLogger().warning("\u041e\u0448\u0438\u0431\u043a\u0430 \u043f\u0440\u0438 \u0444\u043e\u043d\u043e\u0432\u043e\u043c \u0440\u0430\u0441\u0447\u0435\u0442\u0435 \u0442\u043e\u043f\u0430: " + t.getMessage());
        }
    }
}

