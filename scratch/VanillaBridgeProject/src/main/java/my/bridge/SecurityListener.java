/*
 * Decompiled with CFR 0.152.
 * 
 * Could not load the following classes:
 *  io.papermc.paper.event.player.AsyncChatEvent
 *  net.kyori.adventure.text.minimessage.MiniMessage
 *  net.kyori.adventure.text.serializer.plain.PlainTextComponentSerializer
 *  org.bukkit.Bukkit
 *  org.bukkit.Location
 *  org.bukkit.entity.Entity
 *  org.bukkit.entity.HumanEntity
 *  org.bukkit.entity.LivingEntity
 *  org.bukkit.entity.Player
 *  org.bukkit.event.EventHandler
 *  org.bukkit.event.EventPriority
 *  org.bukkit.event.Listener
 *  org.bukkit.event.entity.EntityDamageByEntityEvent
 *  org.bukkit.event.entity.EntityDamageEvent
 *  org.bukkit.event.entity.EntityPickupItemEvent
 *  org.bukkit.event.inventory.InventoryClickEvent
 *  org.bukkit.event.inventory.InventoryDragEvent
 *  org.bukkit.event.inventory.InventoryOpenEvent
 *  org.bukkit.event.player.PlayerArmorStandManipulateEvent
 *  org.bukkit.event.player.PlayerCommandPreprocessEvent
 *  org.bukkit.event.player.PlayerDropItemEvent
 *  org.bukkit.event.player.PlayerInteractAtEntityEvent
 *  org.bukkit.event.player.PlayerInteractEntityEvent
 *  org.bukkit.event.player.PlayerInteractEvent
 *  org.bukkit.event.player.PlayerItemHeldEvent
 *  org.bukkit.event.player.PlayerMoveEvent
 *  org.bukkit.event.player.PlayerQuitEvent
 *  org.bukkit.event.player.PlayerSwapHandItemsEvent
 *  org.bukkit.event.player.PlayerTeleportEvent
 *  org.bukkit.event.player.PlayerTeleportEvent$TeleportCause
 *  org.bukkit.event.vehicle.VehicleEnterEvent
 *  org.bukkit.plugin.Plugin
 */
package my.bridge;

import io.papermc.paper.event.player.AsyncChatEvent;
import java.util.Locale;
import my.bridge.SecurityIpManager;
import my.bridge.VanillaBridge;
import net.kyori.adventure.text.minimessage.MiniMessage;
import net.kyori.adventure.text.serializer.plain.PlainTextComponentSerializer;
import org.bukkit.Bukkit;
import org.bukkit.Location;
import org.bukkit.entity.Entity;
import org.bukkit.entity.HumanEntity;
import org.bukkit.entity.LivingEntity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.event.entity.EntityDamageEvent;
import org.bukkit.event.entity.EntityPickupItemEvent;
import org.bukkit.event.inventory.InventoryClickEvent;
import org.bukkit.event.inventory.InventoryDragEvent;
import org.bukkit.event.inventory.InventoryOpenEvent;
import org.bukkit.event.player.PlayerArmorStandManipulateEvent;
import org.bukkit.event.player.PlayerCommandPreprocessEvent;
import org.bukkit.event.player.PlayerDropItemEvent;
import org.bukkit.event.player.PlayerInteractAtEntityEvent;
import org.bukkit.event.player.PlayerInteractEntityEvent;
import org.bukkit.event.player.PlayerInteractEvent;
import org.bukkit.event.player.PlayerItemHeldEvent;
import org.bukkit.event.player.PlayerMoveEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.event.player.PlayerSwapHandItemsEvent;
import org.bukkit.event.player.PlayerTeleportEvent;
import org.bukkit.event.vehicle.VehicleEnterEvent;
import org.bukkit.plugin.Plugin;

public class SecurityListener
implements Listener {
    private final VanillaBridge plugin;
    private final SecurityIpManager manager;

    public SecurityListener(VanillaBridge plugin, SecurityIpManager manager) {
        this.plugin = plugin;
        this.manager = manager;
    }

    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onMove(PlayerMoveEvent event) {
        Player player = event.getPlayer();
        if (!this.manager.isPending2FA(player.getUniqueId())) {
            return;
        }
        Location from = event.getFrom();
        Location to = event.getTo();
        if (to == null) {
            return;
        }
        if (from.getX() != to.getX() || from.getY() != to.getY() || from.getZ() != to.getZ()) {
            Location newLoc = from.clone();
            newLoc.setYaw(to.getYaw());
            newLoc.setPitch(to.getPitch());
            event.setTo(newLoc);
        }
    }

    @EventHandler(priority=EventPriority.LOWEST)
    public void onChat(AsyncChatEvent event) {
        Player player = event.getPlayer();
        if (!this.manager.isPending2FA(player.getUniqueId())) {
            return;
        }
        event.setCancelled(true);
        String rawText = PlainTextComponentSerializer.plainText().serialize(event.message()).trim();
        if (rawText.matches("^\\d{6}$")) {
            Bukkit.getScheduler().runTask((Plugin)this.plugin, () -> this.manager.checkCode(player, rawText));
            return;
        }
        player.sendMessage(MiniMessage.miniMessage().deserialize("<red>\u274c \u0427\u0430\u0442 \u0437\u0430\u0431\u043b\u043e\u043a\u0438\u0440\u043e\u0432\u0430\u043d \u0432\u043e \u0432\u0440\u0435\u043c\u044f \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0438\u044f \u0432\u0445\u043e\u0434\u0430!</red>\n<gray>\u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u0442\u0435 \u0432\u0445\u043e\u0434 \u0432 Discord \u043a\u043d\u043e\u043f\u043a\u043e\u0439 \u0438\u043b\u0438 \u0432\u0432\u0435\u0434\u0438\u0442\u0435 6 \u0446\u0438\u0444\u0440: <yellow>/code [6 \u0446\u0438\u0444\u0440]</yellow></gray>"));
    }

    @EventHandler(priority=EventPriority.LOWEST)
    public void onCommand(PlayerCommandPreprocessEvent event) {
        Player player = event.getPlayer();
        if (!this.manager.isPending2FA(player.getUniqueId())) {
            return;
        }
        String cmd = event.getMessage().trim().toLowerCase(Locale.ROOT);
        if (cmd.startsWith("/code") || cmd.startsWith("/\u043a\u043e\u0434") || cmd.startsWith("/auth") || cmd.startsWith("/confirm")) {
            return;
        }
        event.setCancelled(true);
        player.sendMessage(MiniMessage.miniMessage().deserialize("<red>\u274c \u041a\u043e\u043c\u0430\u043d\u0434\u044b \u0437\u0430\u0431\u043b\u043e\u043a\u0438\u0440\u043e\u0432\u0430\u043d\u044b \u0432\u043e \u0432\u0440\u0435\u043c\u044f \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0438\u044f \u0432\u0445\u043e\u0434\u0430!</red>\n<gray>\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043a\u043e\u0434 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u0438\u044f: <yellow>/code [6 \u0446\u0438\u0444\u0440]</yellow> \u0438\u043b\u0438 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u0442\u0435 \u0432 Discord \u043a\u043d\u043e\u043f\u043a\u043e\u0439.</gray>"));
    }

    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onDropItem(PlayerDropItemEvent event) {
        if (this.manager.isPending2FA(event.getPlayer().getUniqueId())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onPickupItem(EntityPickupItemEvent event) {
        Player p;
        LivingEntity livingEntity = event.getEntity();
        if (livingEntity instanceof Player && this.manager.isPending2FA((p = (Player)livingEntity).getUniqueId())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onInteract(PlayerInteractEvent event) {
        if (this.manager.isPending2FA(event.getPlayer().getUniqueId())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onInventoryClick(InventoryClickEvent event) {
        Player p;
        HumanEntity humanEntity = event.getWhoClicked();
        if (humanEntity instanceof Player && this.manager.isPending2FA((p = (Player)humanEntity).getUniqueId())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onInventoryDrag(InventoryDragEvent event) {
        Player p;
        HumanEntity humanEntity = event.getWhoClicked();
        if (humanEntity instanceof Player && this.manager.isPending2FA((p = (Player)humanEntity).getUniqueId())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onInventoryOpen(InventoryOpenEvent event) {
        Player p;
        HumanEntity humanEntity = event.getPlayer();
        if (humanEntity instanceof Player && this.manager.isPending2FA((p = (Player)humanEntity).getUniqueId())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onDamage(EntityDamageEvent event) {
        Player p;
        Entity entity = event.getEntity();
        if (entity instanceof Player && this.manager.isPending2FA((p = (Player)entity).getUniqueId())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onDamageByEntity(EntityDamageByEntityEvent event) {
        Player p;
        Entity entity = event.getDamager();
        if (entity instanceof Player && this.manager.isPending2FA((p = (Player)entity).getUniqueId())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onItemHeld(PlayerItemHeldEvent event) {
        if (this.manager.isPending2FA(event.getPlayer().getUniqueId())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onSwapHands(PlayerSwapHandItemsEvent event) {
        if (this.manager.isPending2FA(event.getPlayer().getUniqueId())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onInteractEntity(PlayerInteractEntityEvent event) {
        if (this.manager.isPending2FA(event.getPlayer().getUniqueId())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onInteractAtEntity(PlayerInteractAtEntityEvent event) {
        if (this.manager.isPending2FA(event.getPlayer().getUniqueId())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onVehicleEnter(VehicleEnterEvent event) {
        Player p;
        Entity entity = event.getEntered();
        if (entity instanceof Player && this.manager.isPending2FA((p = (Player)entity).getUniqueId())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onArmorStandManipulate(PlayerArmorStandManipulateEvent event) {
        if (this.manager.isPending2FA(event.getPlayer().getUniqueId())) {
            event.setCancelled(true);
        }
    }

    @EventHandler(priority=EventPriority.HIGHEST, ignoreCancelled=true)
    public void onTeleport(PlayerTeleportEvent event) {
        if (this.manager.isPending2FA(event.getPlayer().getUniqueId()) && (event.getCause() == PlayerTeleportEvent.TeleportCause.NETHER_PORTAL || event.getCause() == PlayerTeleportEvent.TeleportCause.END_PORTAL || event.getCause() == PlayerTeleportEvent.TeleportCause.ENDER_PEARL || event.getCause() == PlayerTeleportEvent.TeleportCause.CHORUS_FRUIT)) {
            event.setCancelled(true);
        }
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent event) {
        this.manager.cancel(event.getPlayer().getUniqueId());
    }
}

