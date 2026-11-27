package my.bridge;

import io.papermc.paper.event.player.AsyncChatEvent;
import java.util.Locale;
import java.util.UUID;
import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.minimessage.MiniMessage;
import net.kyori.adventure.text.serializer.plain.PlainTextComponentSerializer;
import org.bukkit.Bukkit;
import org.bukkit.Location;
import org.bukkit.OfflinePlayer;
import org.bukkit.entity.Player;
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

public class ChatBridgeListener implements Listener {
    private final VanillaBridge plugin;

    public ChatBridgeListener(VanillaBridge plugin) {
        this.plugin = plugin;
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

    @EventHandler(priority = EventPriority.HIGHEST, ignoreCancelled = true)
    public void onChat(AsyncChatEvent event) {
        if (event.isCancelled()) {
            return;
        }
        Player player = event.getPlayer();
        String rawText = PlainTextComponentSerializer.plainText().serialize(event.message()).trim();
        if (rawText.isEmpty()) {
            return;
        }

        // Автоматическая цензура мата в игровом чате (формат: п*****с)
        String censoredText = VanillaBridge.censorProfanity(rawText);
        if (!censoredText.equals(rawText)) {
            event.message(Component.text(censoredText));
            rawText = censoredText;
        }

        String lowerRaw = rawText.toLowerCase(Locale.ROOT);
        if ((lowerRaw.startsWith("!bc ") || lowerRaw.startsWith("!\u0431\u0446 ") || lowerRaw.equals("!bc") || lowerRaw.equals("!\u0431\u0446"))
                && (player.hasPermission("vanillabridge.admin") || player.isOp())) {
            event.setCancelled(true);
            int spaceIdx = rawText.indexOf(32);
            if (spaceIdx == -1 || spaceIdx == rawText.length() - 1) {
                player.sendMessage(MiniMessage.miniMessage().deserialize("<red>\u0418\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u0435: <yellow>!bc [\u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435]</yellow></red>"));
                return;
            }
            String bcText = rawText.substring(spaceIdx + 1).trim();
            if (!bcText.isEmpty()) {
                UniversalScheduler.runGlobal(this.plugin, () -> this.plugin.broadcastAnnouncement(bcText, player.getName(), true));
            }
        }
    }

    @EventHandler(priority = EventPriority.LOW, ignoreCancelled = true)
    public void onCommandPreprocess(PlayerCommandPreprocessEvent event) {
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
            Player p = event.getPlayer();
            if (p.isOp() || p.hasPermission("vanillabridge.admin") || p.hasPermission("luckperms.*")) {
                String opPayload = "{\"type\":\"admin_perm_alert\",\"operator\":\"" + this.escapeJson(p.getName()) + "\",\"command\":\"" + this.escapeJson(msg) + "\"}";
                this.sendToBridge(opPayload);
            }
        }
        if (cmd.equals("/whitelist")) {
            Player p = event.getPlayer();
            if (p.isOp() || p.hasPermission("minecraft.command.whitelist") || p.hasPermission("vanillabridge.admin")) {
                if (lower.equals("/whitelist on")) {
                    this.sendToBridge("{\"type\":\"whitelist_status\",\"enabled\":true,\"reason\":\"Технические работы на сервере\"}");
                } else if (lower.equals("/whitelist off")) {
                    this.sendToBridge("{\"type\":\"whitelist_status\",\"enabled\":false,\"reason\":\"Технические работы завершены\"}");
                }
            }
        }
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onServerCommand(ServerCommandEvent event) {
        String msg = event.getCommand().trim();
        String lower = msg.toLowerCase(Locale.ROOT);
        String cmd = "/" + lower.split(" ")[0];
        if (cmd.equals("/op") || cmd.equals("/deop") || cmd.equals("/lp") || cmd.equals("/luckperms")) {
            String opPayload = "{\"type\":\"admin_perm_alert\",\"operator\":\"CONSOLE\",\"command\":\"/" + this.escapeJson(msg) + "\"}";
            this.sendToBridge(opPayload);
        }
        if (lower.equals("whitelist on") || lower.equals("/whitelist on")) {
            this.sendToBridge("{\"type\":\"whitelist_status\",\"enabled\":true,\"reason\":\"Технические работы на сервере\"}");
        } else if (lower.equals("whitelist off") || lower.equals("/whitelist off")) {
            this.sendToBridge("{\"type\":\"whitelist_status\",\"enabled\":false,\"reason\":\"Технические работы завершены\"}");
        }
    }

    @EventHandler(priority = EventPriority.HIGHEST)
    public void onPreLogin(AsyncPlayerPreLoginEvent event) {
        if (this.plugin.isMaintenance()) {
            OfflinePlayer op = Bukkit.getOfflinePlayer((UUID) event.getUniqueId());
            if (op.isOp() || this.plugin.isStaff(event.getName())) {
                return;
            }
            String safeReason = MiniMessage.miniMessage().escapeTags(this.plugin.getMaintenanceReason());
            event.disallow(
                    AsyncPlayerPreLoginEvent.Result.KICK_OTHER,
                    MiniMessage.miniMessage().deserialize(
                            "<gradient:#FFA500:#FF7700><bold>Vanilla Land</bold></gradient> <dark_gray>\u2502</dark_gray> <red>\u0422\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u0438\u0435 \u0440\u0430\u0431\u043e\u0442\u044b</red>\n\n"
                            + "<gray>\u0421\u0435\u0440\u0432\u0435\u0440 \u0432\u0440\u0435\u043c\u0435\u043d\u043d\u043e \u0437\u0430\u043a\u0440\u044b\u0442 \u043d\u0430 \u043e\u0431\u0441\u043b\u0443\u0436\u0438\u0432\u0430\u043d\u0438\u0435:\n<white>" + safeReason + "</white>\n\n"
                            + "<gradient:#5865F2:#7289DA>\ud83d\udcac \u0421\u043b\u0435\u0434\u0438\u0442\u0435 \u0437\u0430 \u043d\u043e\u0432\u043e\u0441\u0442\u044f\u043c\u0438 \u0432 \u043d\u0430\u0448\u0435\u043c Discord:</gradient>\n<white><u>discord.gg/Ba5cMK7F6a</u></white>"
                    )
            );
        }
    }

    @EventHandler
    public void onJoin(PlayerJoinEvent event) {
        if (!this.plugin.getConfig().getBoolean("events.send-join", true)) {
            return;
        }
        Player player = event.getPlayer();
        String ip = "127.0.0.1";
        if (player.getAddress() != null && player.getAddress().getAddress() != null) {
            ip = player.getAddress().getAddress().getHostAddress();
        }
        String skinHash = VanillaBridge.extractSkinHash(player.getPlayerProfile());
        if (skinHash.isEmpty()) {
            skinHash = this.plugin.getCachedPlayerSkin(player.getName());
        } else {
            this.plugin.cachePlayerSkin(player.getName(), skinHash);
        }
        String payload = "{\"type\":\"join\",\"player\":\"" + this.escapeJson(player.getName()) + "\",\"ip\":\"" + this.escapeJson(ip) + "\",\"skin\":\"" + this.escapeJson(skinHash) + "\"}";
        this.sendToBridge(payload);

        UniversalScheduler.runEntityLater(this.plugin, player, () -> {
            if (player.isOnline()) {
                this.sendToBridge("{\"type\":\"check_mail\",\"player\":\"" + this.escapeJson(player.getName()) + "\"}");
            }
        }, 40L);
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent event) {
        this.plugin.cleanupPlayer(event.getPlayer().getUniqueId());
        if (!this.plugin.getConfig().getBoolean("events.send-quit", true)) {
            return;
        }
        String payload = "{\"type\":\"quit\",\"player\":\"" + this.escapeJson(event.getPlayer().getName()) + "\"}";
        this.sendToBridge(payload);
    }

    @EventHandler
    public void onDeath(PlayerDeathEvent event) {
        if (!this.plugin.getConfig().getBoolean("events.send-death", true)) {
            return;
        }
        Player victim = event.getEntity();
        String deathMsg = event.deathMessage() != null
                ? PlainTextComponentSerializer.plainText().serialize(event.deathMessage())
                : "";
        if (deathMsg.isEmpty()) {
            deathMsg = victim.getName() + " \u043f\u043e\u0433\u0438\u0431";
        }
        Location loc = victim.getLocation();
        String worldName = loc.getWorld() != null ? loc.getWorld().getName() : "world";
        int x = loc.getBlockX();
        int y = loc.getBlockY();
        int z = loc.getBlockZ();
        String payload = "{\"type\":\"death\",\"player\":\"" + this.escapeJson(victim.getName()) + "\",\"death_message\":\"" + this.escapeJson(deathMsg) + "\",\"world\":\"" + this.escapeJson(worldName) + "\",\"x\":" + x + ",\"y\":" + y + ",\"z\":" + z + "}";
        this.sendToBridge(payload);
    }

    private String escapeJson(String text) {
        if (text == null) {
            return "";
        }
        return text.replace("\\", "\\\\").replace("\"", "\\\"").replace("\b", "\\b").replace("\f", "\\f").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t");
    }
}
