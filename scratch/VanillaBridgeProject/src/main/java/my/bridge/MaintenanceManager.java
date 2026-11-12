package my.bridge;

import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.minimessage.MiniMessage;
import org.bukkit.Bukkit;
import org.bukkit.Sound;
import org.bukkit.entity.Player;
import org.bukkit.plugin.Plugin;
import org.bukkit.scheduler.BukkitRunnable;
import org.bukkit.scheduler.BukkitTask;

import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

public class MaintenanceManager {

    private final VanillaBridge plugin;
    private final Set<String> staffWhitelist = Collections.synchronizedSet(new HashSet<>());
    private boolean maintenanceActive = false;
    private String maintenanceReason = "Плановые технические работы";

    private BukkitTask countdownTask = null;
    private int remainingSeconds = 0;
    private String countdownMode = "maintenance";
    private String countdownReason = "";

    public MaintenanceManager(VanillaBridge plugin) {
        this.plugin = plugin;
    }

    public boolean isMaintenance() {
        return this.maintenanceActive;
    }

    public void setMaintenance(boolean active, String reason) {
        this.maintenanceActive = active;
        if (reason != null && !reason.trim().isEmpty()) {
            this.maintenanceReason = reason.trim();
        }
    }

    public String getMaintenanceReason() {
        return this.maintenanceReason;
    }

    public boolean isStaff(String name) {
        if (name == null || name.isEmpty()) return false;
        return this.staffWhitelist.contains(name.toLowerCase());
    }

    public void updateStaffWhitelist(List<String> list) {
        this.staffWhitelist.clear();
        if (list != null) {
            for (String s : list) {
                if (s != null && !s.trim().isEmpty()) {
                    this.staffWhitelist.add(s.trim().toLowerCase());
                }
            }
        }
        this.plugin.getLogger().info("Синхронизирован белый список персонала: " + this.staffWhitelist.size() + " игроков");
    }

    public void startMaintenanceCountdown(String mode, int totalSec, String reason) {
        if (this.countdownTask != null) {
            this.countdownTask.cancel();
            this.countdownTask = null;
        }

        final boolean isRestart = "restart".equalsIgnoreCase(mode);
        final String actionName = isRestart ? "рестарта" : "техработ";
        final String actualReason = (reason != null && !reason.trim().isEmpty())
            ? reason.trim()
            : (isRestart ? "Плановая перезагрузка сервера" : "Техническое обслуживание сервера");
        final String safeReason = MiniMessage.miniMessage().escapeTags(actualReason);

        this.remainingSeconds = totalSec;
        this.countdownMode = mode;
        this.countdownReason = actualReason;

        String initTimeStr = totalSec >= 60 ? (totalSec / 60) + " мин." : totalSec + " сек.";
        Component banner = MiniMessage.miniMessage().deserialize(
            "\n<gradient:#FFA500:#FF7700>✧ ── ⌛ ОБЪЯВЛЕНИЕ " + (isRestart ? "О РЕСТАРТЕ" : "О ТЕХРАБОТАХ") + " ── ✧</gradient>\n"
            + "  <yellow>До " + actionName + " осталось: <bold>" + initTimeStr + "</bold></yellow>\n"
            + "  <gray>Причина: <white>" + safeReason + "</white></gray>\n"
            + "<gradient:#FFA500:#FF7700>✧ ──────────────────────── ✧</gradient>\n"
        );

        for (Player p : Bukkit.getOnlinePlayers()) {
            p.sendMessage(banner);
            try {
                p.playSound(p.getLocation(), Sound.BLOCK_NOTE_BLOCK_BELL, 1.0f, 1.0f);
            } catch (Exception ignored) {}
        }

        this.countdownTask = new BukkitRunnable() {
            @Override
            public void run() {
                remainingSeconds--;
                if (remainingSeconds <= 0) {
                    cancel();
                    countdownTask = null;
                    if (isRestart) {
                        Bukkit.broadcast(MiniMessage.miniMessage().deserialize("<red><bold>Сервер перезагружается прямо сейчас...</bold></red>"));
                        Bukkit.shutdown();
                    } else {
                        maintenanceActive = true;
                        maintenanceReason = actualReason;
                        Component kickMsg = MiniMessage.miniMessage().deserialize(
                            "<gradient:#ff7a00:#ffae19><bold>Vanilla Land</bold></gradient>\n\n"
                            + "<red>Сервер закрыт на технические работы.</red>\n"
                            + "<gray>Причина: <white>" + safeReason + "</white></gray>\n\n"
                            + "<yellow>Следите за новостями в нашем Discord: discord.gg/Ba5cMK7F6a</yellow>"
                        );
                        for (Player p : Bukkit.getOnlinePlayers()) {
                            if (!isStaff(p.getName()) && !p.hasPermission("vanillabridge.admin")) {
                                p.kick(kickMsg);
                            }
                        }
                    }
                    return;
                }

                if (remainingSeconds == 300 || remainingSeconds == 180 || remainingSeconds == 120 || remainingSeconds == 60 || remainingSeconds == 30 || remainingSeconds <= 10) {
                    String timeStr = remainingSeconds >= 60 ? (remainingSeconds / 60) + " мин." : remainingSeconds + " сек.";
                    Component alert = MiniMessage.miniMessage().deserialize(
                        "<gradient:#ff7a00:#ffae19><bold>Внимание!</bold></gradient> <yellow>До " + actionName + " осталось: <bold>" + timeStr + "</bold></yellow>"
                    );
                    for (Player p : Bukkit.getOnlinePlayers()) {
                        p.sendMessage(alert);
                        try {
                            p.playSound(p.getLocation(), Sound.BLOCK_NOTE_BLOCK_PLING, 1.0f, 1.5f);
                        } catch (Exception ignored) {}
                    }
                }
            }
        }.runTaskTimer(this.plugin, 20L, 20L);
    }

    public void extendMaintenanceCountdown(int extraSec) {
        if (this.countdownTask != null) {
            this.remainingSeconds += extraSec;
            String timeStr = this.remainingSeconds >= 60 ? (this.remainingSeconds / 60) + " мин." : this.remainingSeconds + " сек.";
            Bukkit.broadcast(MiniMessage.miniMessage().deserialize(
                "<green>Время до " + ("restart".equalsIgnoreCase(this.countdownMode) ? "рестарта" : "техработ") + " продлено на " + extraSec + " сек. Осталось: <bold>" + timeStr + "</bold></green>"
            ));
        }
    }

    public void cancelMaintenanceCountdown() {
        if (this.countdownTask != null) {
            this.countdownTask.cancel();
            this.countdownTask = null;
            this.remainingSeconds = 0;
            Bukkit.broadcast(MiniMessage.miniMessage().deserialize("<green><bold>Отсчёт до технических работ / рестарта отменён администратором.</bold></green>"));
        }
    }
}
