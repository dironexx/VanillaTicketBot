/*
 * Decompiled with CFR 0.152.
 * 
 * Could not load the following classes:
 *  io.papermc.paper.event.player.AsyncChatEvent
 *  net.kyori.adventure.audience.Audience
 *  net.kyori.adventure.text.Component
 *  net.kyori.adventure.text.minimessage.MiniMessage
 *  net.kyori.adventure.text.serializer.plain.PlainTextComponentSerializer
 *  org.bukkit.Bukkit
 *  org.bukkit.Location
 *  org.bukkit.OfflinePlayer
 *  org.bukkit.entity.Player
 *  org.bukkit.event.Event
 *  org.bukkit.event.EventHandler
 *  org.bukkit.event.EventPriority
 *  org.bukkit.event.Listener
 *  org.bukkit.event.entity.PlayerDeathEvent
 *  org.bukkit.event.player.AsyncPlayerChatEvent
 *  org.bukkit.event.player.AsyncPlayerPreLoginEvent
 *  org.bukkit.event.player.AsyncPlayerPreLoginEvent$Result
 *  org.bukkit.event.player.PlayerCommandPreprocessEvent
 *  org.bukkit.event.player.PlayerJoinEvent
 *  org.bukkit.event.player.PlayerQuitEvent
 *  org.bukkit.event.server.ServerCommandEvent
 *  org.bukkit.plugin.Plugin
 */
package my.bridge;

import io.papermc.paper.event.player.AsyncChatEvent;
import java.lang.reflect.Method;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import my.bridge.VanillaBridge;
import net.kyori.adventure.audience.Audience;
import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.minimessage.MiniMessage;
import net.kyori.adventure.text.serializer.plain.PlainTextComponentSerializer;
import org.bukkit.Bukkit;
import org.bukkit.Location;
import org.bukkit.OfflinePlayer;
import org.bukkit.entity.Player;
import org.bukkit.event.Event;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.PlayerDeathEvent;
import org.bukkit.event.player.AsyncPlayerChatEvent;
import org.bukkit.event.player.AsyncPlayerPreLoginEvent;
import org.bukkit.event.player.PlayerCommandPreprocessEvent;
import org.bukkit.event.player.PlayerJoinEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.event.server.ServerCommandEvent;
import org.bukkit.plugin.Plugin;

public class ChatBridgeListener
implements Listener {
    private final VanillaBridge plugin;
    private final Map<String, Long> recentSentMessages = new ConcurrentHashMap<String, Long>();

    public ChatBridgeListener(VanillaBridge plugin) {
        this.plugin = plugin;
        this.registerChattyListener();
    }

    private void sendToBridge(String payload) {
        try {
            BridgeClient client = this.plugin.getBridgeClient();
            if (client != null && client.isConnected()) {
                client.send(payload);
            }
        } catch (Exception ignored) {
        }
    }

    @EventHandler(priority=EventPriority.LOW, ignoreCancelled=false)
    public void onChat(AsyncChatEvent event) {
        String messageToSend;
        Player player = event.getPlayer();
        if (this.isPlayerMuted(player)) {
            return;
        }
        if (this.plugin.getAuthMeHook() != null && !this.plugin.getAuthMeHook().isAuthenticated(player)) {
            return;
        }
        String rawText = PlainTextComponentSerializer.plainText().serialize(event.message()).trim();
        if (rawText.isEmpty()) {
            return;
        }
        String lowerRaw = rawText.toLowerCase(Locale.ROOT);
        if ((lowerRaw.startsWith("!bc ") || lowerRaw.startsWith("!\u0431\u0446 ") || lowerRaw.equals("!bc") || lowerRaw.equals("!\u0431\u0446")) && (player.hasPermission("vanillabridge.admin") || player.isOp())) {
            event.setCancelled(true);
            int spaceIdx = rawText.indexOf(32);
            if (spaceIdx == -1 || spaceIdx == rawText.length() - 1) {
                player.sendMessage(MiniMessage.miniMessage().deserialize("<red>\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u0435: <yellow>!bc [\u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435]</yellow></red>"));
                return;
            }
            String bcText = rawText.substring(spaceIdx + 1).trim();
            if (!bcText.isEmpty()) {
                Bukkit.getScheduler().runTask((Plugin)this.plugin, () -> this.plugin.broadcastAnnouncement(bcText, player.getName(), true));
            }
            return;
        }
        if (!this.isGlobalChat(event, rawText, player)) {
            return;
        }
        String string = messageToSend = rawText.startsWith("!") ? rawText.substring(1).trim() : rawText;
        if (messageToSend.isEmpty()) {
            return;
        }
        this.sendChatToDiscord(player, messageToSend);
    }

    @EventHandler(priority=EventPriority.LOW, ignoreCancelled=false)
    public void onLegacyChat(AsyncPlayerChatEvent event) {
        String tagArea;
        String rawText;
        Player player = event.getPlayer();
        if (this.isPlayerMuted(player)) {
            return;
        }
        if (this.plugin.getAuthMeHook() != null && !this.plugin.getAuthMeHook().isAuthenticated(player)) {
            return;
        }
        String string = rawText = event.getMessage() != null ? event.getMessage().trim() : "";
        if (rawText.isEmpty()) {
            return;
        }
        if (rawText.startsWith("!")) {
            String messageToSend = rawText.substring(1).trim();
            if (!messageToSend.isEmpty()) {
                this.sendChatToDiscord(player, messageToSend);
            }
            return;
        }
        String mode = ChatBridgeListener.getPlayerChatMode(player.getUniqueId());
        if (mode != null) {
            if ("GLOBAL".equalsIgnoreCase(mode)) {
                this.sendChatToDiscord(player, rawText);
                return;
            }
            if ("LOCAL".equalsIgnoreCase(mode) || "PRIVATE".equalsIgnoreCase(mode) || "PARTY".equalsIgnoreCase(mode)) {
                return;
            }
        }
        if (this.isChattyGlobal(player)) {
            this.sendChatToDiscord(player, rawText);
            return;
        }
        String format = event.getFormat() != null ? ChatBridgeListener.normalizeChannelTag(event.getFormat()) : "";
        String string2 = tagArea = format.length() > 60 ? format.substring(0, 60) : format;
        if (ChatBridgeListener.isLocalTag(tagArea)) {
            return;
        }
        if (ChatBridgeListener.isGlobalTag(tagArea)) {
            this.sendChatToDiscord(player, rawText);
            return;
        }
        try {
            int online = Bukkit.getOnlinePlayers().size();
            int recipients = event.getRecipients().size();
            if (online > 1 && recipients < online) {
                return;
            }
        }
        catch (Throwable throwable) {
            // empty catch block
        }
        this.sendChatToDiscord(player, rawText);
    }

    private boolean isGlobalChat(AsyncChatEvent event, String rawText, Player player) {
        if (rawText.startsWith("!")) {
            return true;
        }
        String mode = ChatBridgeListener.getPlayerChatMode(player.getUniqueId());
        if (mode != null) {
            if ("GLOBAL".equalsIgnoreCase(mode)) {
                return true;
            }
            if ("LOCAL".equalsIgnoreCase(mode) || "PRIVATE".equalsIgnoreCase(mode) || "PARTY".equalsIgnoreCase(mode)) {
                return false;
            }
        }
        if (this.isChattyGlobal(player)) {
            return true;
        }
        try {
            String tagArea;
            Component rendered = event.renderer().render(player, player.displayName(), event.message(), (Audience)Bukkit.getConsoleSender());
            String plain = PlainTextComponentSerializer.plainText().serialize(rendered);
            String norm = ChatBridgeListener.normalizeChannelTag(plain);
            String string = tagArea = norm.length() > 60 ? norm.substring(0, 60) : norm;
            if (ChatBridgeListener.isLocalTag(tagArea)) {
                return false;
            }
            if (ChatBridgeListener.isGlobalTag(tagArea)) {
                return true;
            }
        }
        catch (Throwable rendered) {
            // empty catch block
        }
        try {
            int online = Bukkit.getOnlinePlayers().size();
            int viewers = event.viewers().size();
            if (online > 1 && viewers < online) {
                return false;
            }
        }
        catch (Throwable throwable) {
            // empty catch block
        }
        return true;
    }

    public void sendChatToDiscord(Player player, String message) {
        String skinHash;
        if (message == null || message.trim().isEmpty()) {
            return;
        }
        String text = message.trim();
        String dedupKey = player.getName().toLowerCase(Locale.ROOT) + ":" + text;
        long now = System.currentTimeMillis();
        Long lastTime = this.recentSentMessages.get(dedupKey);
        if (lastTime != null && now - lastTime < 1500L) {
            return;
        }
        this.recentSentMessages.put(dedupKey, now);
        if (this.recentSentMessages.size() > 200) {
            this.recentSentMessages.entrySet().removeIf(e -> now - (Long)e.getValue() > 10000L);
        }
        if ((skinHash = VanillaBridge.extractSkinHash(player.getPlayerProfile())).isEmpty()) {
            skinHash = this.plugin.getCachedPlayerSkin(player.getName());
        } else {
            this.plugin.cachePlayerSkin(player.getName(), skinHash);
        }
        String payload = "{\"type\":\"chat\",\"player\":\"" + this.escapeJson(player.getName()) + "\",\"skin\":\"" + this.escapeJson(skinHash) + "\",\"message\":\"" + this.escapeJson(text) + "\"}";
        this.sendToBridge(payload);
    }

    @EventHandler(priority=EventPriority.LOW, ignoreCancelled=false)
    public void onCommandPreprocess(PlayerCommandPreprocessEvent event) {
        String chatMsg;
        int firstSpace;
        int secondSpace;
        String[] parts;
        String msg = event.getMessage().trim();
        String lower = msg.toLowerCase(Locale.ROOT);
        String cmd = lower.split(" ")[0];
        if (cmd.equals("/bc") || cmd.equals("/broadcast") || cmd.equals("/vbc") || cmd.equals("/\u043e\u0431\u044a\u044f\u0432\u043b\u0435\u043d\u0438\u0435") || cmd.equals("/\u043e\u0431")) {
            Player player = event.getPlayer();
            if (!player.hasPermission("vanillabridge.admin") && !player.isOp()) {
                return;
            }
            event.setCancelled(true);
            int firstSpace2 = msg.indexOf(32);
            if (firstSpace2 == -1 || firstSpace2 == msg.length() - 1) {
                player.sendMessage(MiniMessage.miniMessage().deserialize("<red>\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u0435: <yellow>/bc [\u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435]</yellow></red>"));
                return;
            }
            String broadcastText = msg.substring(firstSpace2 + 1).trim();
            if (broadcastText.isEmpty()) {
                player.sendMessage(MiniMessage.miniMessage().deserialize("<red>\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u0435: <yellow>/bc [\u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435]</yellow></red>"));
                return;
            }
            this.plugin.broadcastAnnouncement(broadcastText, player.getName(), true);
            return;
        }
        if (cmd.equals("/g") || cmd.equals("/global") || cmd.equals("/shout") || cmd.equals("/\u0433")) {
            String chatMsg2;
            int firstSpace3 = msg.indexOf(32);
            if (firstSpace3 != -1 && firstSpace3 < msg.length() - 1 && !(chatMsg2 = msg.substring(firstSpace3 + 1).trim()).isEmpty()) {
                this.sendChatToDiscord(event.getPlayer(), chatMsg2);
            }
            return;
        }
        if ((cmd.equals("/c") || cmd.equals("/chat")) && (parts = msg.split("\\s+")).length >= 3 && (parts[1].equalsIgnoreCase("global") || parts[1].equalsIgnoreCase("g")) && (secondSpace = msg.indexOf(32, (firstSpace = msg.indexOf(32)) + 1)) != -1 && secondSpace < msg.length() - 1 && !(chatMsg = msg.substring(secondSpace + 1).trim()).isEmpty()) {
            this.sendChatToDiscord(event.getPlayer(), chatMsg);
        }
        if (cmd.equals("/links") || cmd.equals("/\u0441\u0441\u044b\u043b\u043a\u0438") || cmd.equals("/linki")) {
            event.setCancelled(true);
            event.getPlayer().sendMessage(this.plugin.buildLinksComponent());
            return;
        }
        if (cmd.equals("/discord") || cmd.equals("/ds") || cmd.equals("/\u0434\u0441")) {
            event.setCancelled(true);
            event.getPlayer().sendMessage(this.plugin.buildDiscordComponent());
            return;
        }
        if (cmd.equals("/site") || cmd.equals("/\u0441\u0430\u0439\u0442") || cmd.equals("/website")) {
            event.setCancelled(true);
            event.getPlayer().sendMessage(this.plugin.buildSiteComponent());
            return;
        }
        if (cmd.equals("/donate") || cmd.equals("/\u0434\u043e\u043d\u0430\u0442") || cmd.equals("/store") || cmd.equals("/shop") || cmd.equals("/\u043c\u0430\u0433\u0430\u0437\u0438\u043d")) {
            event.setCancelled(true);
            event.getPlayer().sendMessage(this.plugin.buildDonateComponent());
            return;
        }
        if (cmd.equals("/telegram") || cmd.equals("/tg") || cmd.equals("/\u0442\u0433")) {
            event.setCancelled(true);
            event.getPlayer().sendMessage(this.plugin.buildTelegramComponent());
            return;
        }
        if (cmd.equals("/op") || cmd.equals("/deop") || cmd.equals("/lp") || cmd.equals("/luckperms")) {
            String opPayload = "{\"type\":\"admin_perm_alert\",\"operator\":\"" + this.escapeJson(event.getPlayer().getName()) + "\",\"command\":\"" + this.escapeJson(msg) + "\"}";
            this.sendToBridge(opPayload);
        }
    }

    @EventHandler(priority=EventPriority.MONITOR)
    public void onServerCommand(ServerCommandEvent event) {
        String msg = event.getCommand().trim();
        String lower = msg.toLowerCase(Locale.ROOT);
        String cmd = "/" + lower.split(" ")[0];
        if (cmd.equals("/op") || cmd.equals("/deop") || cmd.equals("/lp") || cmd.equals("/luckperms")) {
            String opPayload = "{\"type\":\"admin_perm_alert\",\"operator\":\"CONSOLE\",\"command\":\"/" + this.escapeJson(msg) + "\"}";
            this.sendToBridge(opPayload);
        }
    }

    @EventHandler(priority=EventPriority.HIGHEST)
    public void onPreLogin(AsyncPlayerPreLoginEvent event) {
        if (this.plugin.isMaintenance()) {
            OfflinePlayer op = Bukkit.getOfflinePlayer((UUID)event.getUniqueId());
            if (op.isOp() || this.plugin.isStaff(event.getName())) {
                return;
            }
            String safeReason = MiniMessage.miniMessage().escapeTags(this.plugin.getMaintenanceReason());
            event.disallow(AsyncPlayerPreLoginEvent.Result.KICK_OTHER, MiniMessage.miniMessage().deserialize(("<gradient:#FFA500:#FF7700><bold>Vanilla Land</bold></gradient> <dark_gray>\u2502</dark_gray> <red>\u0422\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u0438\u0435 \u0440\u0430\u0431\u043e\u0442\u044b</red>\n\n<gray>\u0421\u0435\u0440\u0432\u0435\u0440 \u0432\u0440\u0435\u043c\u0435\u043d\u043d\u043e \u0437\u0430\u043a\u0440\u044b\u0442 \u043d\u0430 \u043e\u0431\u0441\u043b\u0443\u0436\u0438\u0432\u0430\u043d\u0438\u0435:\n<white>" + safeReason + "</white>\n\n<gradient:#5865F2:#7289DA>\ud83d\udcac \u0421\u043b\u0435\u0434\u0438\u0442\u0435 \u0437\u0430 \u043d\u043e\u0432\u043e\u0441\u0442\u044f\u043c\u0438 \u0432 \u043d\u0430\u0448\u0435\u043c Discord:</gradient>\n<white><u>discord.gg/Ba5cMK7F6a</u></white>")));
        }
    }

    @EventHandler
    public void onJoin(PlayerJoinEvent event) {
        String skinHash;
        if (!this.plugin.getConfig().getBoolean("events.send-join", true)) {
            return;
        }
        Player player = event.getPlayer();
        String ip = "127.0.0.1";
        if (player.getAddress() != null && player.getAddress().getAddress() != null) {
            ip = player.getAddress().getAddress().getHostAddress();
        }
        if ((skinHash = VanillaBridge.extractSkinHash(player.getPlayerProfile())).isEmpty()) {
            skinHash = this.plugin.getCachedPlayerSkin(player.getName());
        } else {
            this.plugin.cachePlayerSkin(player.getName(), skinHash);
        }
        String payload = "{\"type\":\"join\",\"player\":\"" + this.escapeJson(player.getName()) + "\",\"ip\":\"" + this.escapeJson(ip) + "\",\"skin\":\"" + this.escapeJson(skinHash) + "\"}";
        this.sendToBridge(payload);
        if (this.plugin.getAuthMeHook() == null || !this.plugin.getAuthMeHook().isAuthMeAvailable()) {
            Bukkit.getScheduler().runTaskLater((Plugin)this.plugin, () -> {
                if (player.isOnline()) {
                    this.plugin.handlePostLoginCheck(player);
                }
            }, 15L);
        }
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent event) {
        if (!this.plugin.getConfig().getBoolean("events.send-quit", true)) {
            return;
        }
        String payload = "{\"type\":\"quit\",\"player\":\"" + this.escapeJson(event.getPlayer().getName()) + "\"}";
        this.sendToBridge(payload);
    }

    @EventHandler
    public void onDeath(PlayerDeathEvent event) {
        Location loc;
        if (!this.plugin.getConfig().getBoolean("events.send-death", true)) {
            return;
        }
        Player victim = event.getEntity();
        Object deathMsg = PlainTextComponentSerializer.plainText().serialize(event.deathMessage());
        if (((String)deathMsg).isEmpty()) {
            deathMsg = victim.getName() + " \u043f\u043e\u0433\u0438\u0431";
        }
        String worldName = (loc = victim.getLocation()).getWorld() != null ? loc.getWorld().getName() : "world";
        int x = loc.getBlockX();
        int y = loc.getBlockY();
        int z = loc.getBlockZ();
        String payload = "{\"type\":\"death\",\"player\":\"" + this.escapeJson(victim.getName()) + "\",\"death_message\":\"" + this.escapeJson((String)deathMsg) + "\",\"world\":\"" + this.escapeJson(worldName) + "\",\"x\":" + x + ",\"y\":" + y + ",\"z\":" + z + "}";
        this.sendToBridge(payload);
    }

    private boolean isChattyGlobal(Player player) {
        Plugin chatty = Bukkit.getPluginManager().getPlugin("Chatty");
        if (chatty == null || !chatty.isEnabled()) {
            return false;
        }
        try {
            Method getName;
            Object name;
            Method getChatManager = chatty.getClass().getMethod("getChatManager", new Class[0]);
            Object cm = getChatManager.invoke((Object)chatty, new Object[0]);
            Method getChat = cm.getClass().getMethod("getChat", Player.class);
            Object chat = getChat.invoke(cm, player);
            if (chat != null && (name = (getName = chat.getClass().getMethod("getName", new Class[0])).invoke(chat, new Object[0])) != null) {
                String s = ChatBridgeListener.normalizeChannelTag(name.toString());
                if (s.contains("global") || s.contains("\u0433\u043b\u043e\u0431\u0430\u043b") || s.equals("g") || s.equals("\u0433")) {
                    return true;
                }
                if (s.contains("local") || s.contains("\u043b\u043e\u043a\u0430\u043b") || s.equals("l") || s.equals("\u043b")) {
                    return false;
                }
            }
        }
        catch (Throwable getChatManager) {
            // empty catch block
        }
        try {
            Method getName;
            Object name;
            Method getChannel;
            Object ch;
            Class<?> apiClass = Class.forName("ru.mrbrikster.chatty.api.ChattyApi");
            Method get = apiClass.getMethod("get", new Class[0]);
            Object api = get.invoke(null, new Object[0]);
            if (api != null && (ch = (getChannel = api.getClass().getMethod("getChannel", Player.class)).invoke(api, player)) != null && (name = (getName = ch.getClass().getMethod("getName", new Class[0])).invoke(ch, new Object[0])) != null) {
                String s = ChatBridgeListener.normalizeChannelTag(name.toString());
                if (s.contains("global") || s.contains("\u0433\u043b\u043e\u0431\u0430\u043b") || s.equals("g") || s.equals("\u0433")) {
                    return true;
                }
                if (s.contains("local") || s.contains("\u043b\u043e\u043a\u0430\u043b") || s.equals("l") || s.equals("\u043b")) {
                    return false;
                }
            }
        }
        catch (Throwable throwable) {
            // empty catch block
        }
        return false;
    }

    public void registerChattyListener() {
        String[] possibleClasses;
        for (String className : possibleClasses = new String[]{"ru.mrbrikster.chatty.api.event.ChattyMessageEvent", "ru.mrbrikster.chatty.api.events.ChattyMessageEvent"}) {
            try {
                Class<?> eventClass = Class.forName(className);
                Bukkit.getPluginManager().registerEvent(eventClass.asSubclass(Event.class), (Listener)this, EventPriority.HIGHEST, (l, event) -> this.handleChattyMessage(event), (Plugin)this.plugin);
                this.plugin.getLogger().info("\u2713 \u0423\u0441\u043f\u0435\u0448\u043d\u043e \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d \u0441\u043b\u0443\u0448\u0430\u0442\u0435\u043b\u044c Chatty: " + className);
                return;
            }
            catch (ClassNotFoundException eventClass) {
            }
            catch (Throwable t) {
                this.plugin.getLogger().warning("\u041e\u0448\u0438\u0431\u043a\u0430 \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u044f \u0441\u043b\u0443\u0448\u0430\u0442\u0435\u043b\u044f Chatty (" + className + "): " + t.getMessage());
            }
        }
    }

    private void handleChattyMessage(Object event) {
        try {
            String norm;
            Method isCancelledMethod = event.getClass().getMethod("isCancelled", new Class[0]);
            if (((Boolean)isCancelledMethod.invoke(event, new Object[0])).booleanValue()) {
                return;
            }
            Method getPlayerMethod = event.getClass().getMethod("getPlayer", new Class[0]);
            Player p = (Player)getPlayerMethod.invoke(event, new Object[0]);
            if (p == null) {
                return;
            }
            if (this.isPlayerMuted(p)) {
                return;
            }
            if (this.plugin.getAuthMeHook() != null && !this.plugin.getAuthMeHook().isAuthenticated(p)) {
                return;
            }
            Method getChatMethod = null;
            try {
                getChatMethod = event.getClass().getMethod("getChat", new Class[0]);
            }
            catch (NoSuchMethodException e) {
                try {
                    getChatMethod = event.getClass().getMethod("getChannel", new Class[0]);
                }
                catch (NoSuchMethodException noSuchMethodException) {
                    // empty catch block
                }
            }
            if (getChatMethod == null) {
                return;
            }
            Object chat = getChatMethod.invoke(event, new Object[0]);
            if (chat == null) {
                return;
            }
            boolean isGlobal = false;
            boolean isLocal = false;
            try {
                Method getFormatMethod = chat.getClass().getMethod("getFormat", new Class[0]);
                Object fmt = getFormatMethod.invoke(chat, new Object[0]);
                if (fmt != null) {
                    norm = ChatBridgeListener.normalizeChannelTag(fmt.toString());
                    if (ChatBridgeListener.isLocalTag(norm)) {
                        isLocal = true;
                    }
                    if (ChatBridgeListener.isGlobalTag(norm)) {
                        isGlobal = true;
                    }
                }
            }
            catch (Throwable getFormatMethod) {
                // empty catch block
            }
            if (!isGlobal && !isLocal) {
                try {
                    Method getRangeMethod = chat.getClass().getMethod("getRange", new Class[0]);
                    Object r = getRangeMethod.invoke(chat, new Object[0]);
                    if (r instanceof Number) {
                        double rangeVal = ((Number)r).doubleValue();
                        if (rangeVal <= 0.0) {
                            isGlobal = true;
                        } else {
                            isLocal = true;
                        }
                    }
                }
                catch (Throwable getRangeMethod) {
                    // empty catch block
                }
            }
            if (!isGlobal && !isLocal) {
                try {
                    Method getNameMethod = chat.getClass().getMethod("getName", new Class[0]);
                    Object name = getNameMethod.invoke(chat, new Object[0]);
                    if (name != null) {
                        norm = ChatBridgeListener.normalizeChannelTag(name.toString());
                        if (ChatBridgeListener.isLocalTag(norm)) {
                            isLocal = true;
                        }
                        if (ChatBridgeListener.isGlobalTag(norm)) {
                            isGlobal = true;
                        }
                    }
                }
                catch (Throwable getNameMethod) {
                    // empty catch block
                }
            }
            if (isLocal || !isGlobal) {
                return;
            }
            Method getMessageMethod = event.getClass().getMethod("getMessage", new Class[0]);
            String msg = String.valueOf(getMessageMethod.invoke(event, new Object[0]));
            if (msg == null || msg.trim().isEmpty()) {
                return;
            }
            String messageToSend = msg.trim();
            if (messageToSend.startsWith("!")) {
                messageToSend = messageToSend.substring(1).trim();
            }
            if (!messageToSend.isEmpty()) {
                this.sendChatToDiscord(p, messageToSend);
            }
        }
        catch (Throwable throwable) {
            // empty catch block
        }
    }

    public static boolean isLocalTag(String normalizedText) {
        if (normalizedText == null) {
            return false;
        }
        String s = normalizedText.toLowerCase(Locale.ROOT);
        return s.contains("\u043b\u043e\u043a\u0430\u043b\u044c\u043d") || s.contains("local") || s.contains("[l]") || s.contains("[\u043b]") || s.contains("[\u0440\u044f\u0434\u043e\u043c") || s.contains("\u043f\u0440\u0438\u0432\u0430\u0442\u043d");
    }

    public static boolean isGlobalTag(String normalizedText) {
        if (normalizedText == null) {
            return false;
        }
        String s = normalizedText.toLowerCase(Locale.ROOT);
        return s.contains("\u0433\u043b\u043e\u0431\u0430\u043b\u044c\u043d") || s.contains("global") || s.contains("[g]") || s.contains("[\u0433]") || s.contains("[\u043c\u0438\u0440\u043e\u0432") || s.contains("[\u043e\u0431\u0449");
    }

    public static String normalizeChannelTag(String text) {
        if (text == null) {
            return "";
        }
        String s = text.toLowerCase(Locale.ROOT);
        return s.replace('\u1d00', '\u0430').replace('\u028c', '\u0430').replace('^', '\u0430').replace('\u0299', '\u0431').replace('\u1d04', '\u0441').replace('\u1d07', '\u0435').replace('\u0262', '\u0433').replace('\u1d0b', '\u043a').replace('\u029f', '\u043b').replace('\u1d0d', '\u043c').replace('\u029c', '\u043d').replace('\u1d0f', '\u043e').replace('\u1d18', '\u0440').replace('\u1d1b', '\u0442').replace('\u028f', '\u0443');
    }

    public static String getPlayerChatMode(UUID uuid) {
        String[] targetPlugins;
        if (uuid == null) {
            return null;
        }
        for (String string : targetPlugins = new String[]{"VanillaChat", "CustomInteractiveChat", "ChatPlugin", "InteractiveChat"}) {
            String mode;
            Plugin p = Bukkit.getPluginManager().getPlugin(string);
            if (p == null || !p.isEnabled() || (mode = ChatBridgeListener.queryPlayerMode(p, uuid)) == null) continue;
            return mode;
        }
        for (Plugin p : Bukkit.getPluginManager().getPlugins()) {
            String mode;
            if (p == null || !p.isEnabled() || (mode = ChatBridgeListener.queryPlayerMode(p, uuid)) == null) continue;
            return mode;
        }
        return null;
    }

    private static String queryPlayerMode(Plugin plugin, UUID uuid) {
        try {
            Method method = plugin.getClass().getMethod("getPlayerMode", UUID.class);
            Object result = method.invoke((Object)plugin, uuid);
            if (result != null) {
                return result.toString().trim().toUpperCase(Locale.ROOT);
            }
        }
        catch (Throwable throwable) {
            // empty catch block
        }
        return null;
    }

    private boolean isPlayerMuted(Player player) {
        Plugin liteBans;
        if (player == null) {
            return false;
        }
        Plugin ess = Bukkit.getPluginManager().getPlugin("Essentials");
        if (ess != null && ess.isEnabled()) {
            try {
                Method isMuted;
                Method getUser = ess.getClass().getMethod("getUser", Player.class);
                Object user = getUser.invoke((Object)ess, player);
                if (user != null && ((Boolean)(isMuted = user.getClass().getMethod("isMuted", new Class[0])).invoke(user, new Object[0])).booleanValue()) {
                    return true;
                }
            }
            catch (Throwable getUser) {
                // empty catch block
            }
        }
        if ((liteBans = Bukkit.getPluginManager().getPlugin("LiteBans")) != null && liteBans.isEnabled()) {
            try {
                Class<?> dbClass = Class.forName("litebans.api.Database");
                Method get = dbClass.getMethod("get", new Class[0]);
                Object db = get.invoke(null, new Object[0]);
                if (db != null) {
                    String ip;
                    Method isPlayerMuted = dbClass.getMethod("isPlayerMuted", UUID.class, String.class);
                    String string = ip = player.getAddress() != null && player.getAddress().getAddress() != null ? player.getAddress().getAddress().getHostAddress() : "";
                    if (((Boolean)isPlayerMuted.invoke(db, player.getUniqueId(), ip)).booleanValue()) {
                        return true;
                    }
                }
            }
            catch (Throwable throwable) {
                // empty catch block
            }
        }
        return false;
    }

    private String escapeJson(String text) {
        if (text == null) {
            return "";
        }
        return text.replace("\\", "\\\\").replace("\"", "\\\"").replace("\b", "\\b").replace("\f", "\\f").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t");
    }
}

