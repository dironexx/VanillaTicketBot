/*
 * Decompiled with CFR 0.152.
 * 
 * Could not load the following classes:
 *  org.bukkit.Bukkit
 *  org.bukkit.entity.Player
 *  org.bukkit.event.Event
 *  org.bukkit.event.EventPriority
 *  org.bukkit.event.Listener
 *  org.bukkit.plugin.Plugin
 */
package my.bridge;

import java.lang.reflect.Method;
import java.util.logging.Level;
import my.bridge.VanillaBridge;
import org.bukkit.Bukkit;
import org.bukkit.entity.Player;
import org.bukkit.event.Event;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.plugin.Plugin;

public class AuthMeHook {
    private final VanillaBridge plugin;
    private boolean isAuthMeAvailable = false;

    public AuthMeHook(VanillaBridge plugin) {
        this.plugin = plugin;
    }

    public void register() {
        Plugin authMe = Bukkit.getPluginManager().getPlugin("AuthMe");
        if (authMe == null || !authMe.isEnabled()) {
            this.plugin.getLogger().info("\u041f\u043b\u0430\u0433\u0438\u043d AuthMe \u043d\u0435 \u043e\u0431\u043d\u0430\u0440\u0443\u0436\u0435\u043d. 2FA \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0431\u0443\u0434\u0435\u0442 \u0432\u044b\u043f\u043e\u043b\u043d\u044f\u0442\u044c\u0441\u044f \u043f\u0440\u0438 \u0432\u0445\u043e\u0434\u0435 \u043d\u0430 \u0441\u0435\u0440\u0432\u0435\u0440.");
            return;
        }
        try {
            Class<?> loginEventClass = Class.forName("fr.xephi.authme.events.LoginEvent");
            Class<? extends Event> eventClass = loginEventClass.asSubclass(Event.class);
            Bukkit.getPluginManager().registerEvent(eventClass, new Listener() {}, EventPriority.MONITOR, (listener, event) -> {
                try {
                    Method getPlayerMethod = event.getClass().getMethod("getPlayer", new Class[0]);
                    Player player = (Player)getPlayerMethod.invoke((Object)event, new Object[0]);
                    if (player != null && player.isOnline()) {
                        this.plugin.getLogger().info("AuthMe LoginEvent \u0437\u0430\u0444\u0438\u043a\u0441\u0438\u0440\u043e\u0432\u0430\u043d \u0434\u043b\u044f " + player.getName() + ", \u0437\u0430\u043f\u0443\u0441\u043a \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0438 2FA...");
                        this.plugin.handlePostLoginCheck(player);
                    }
                }
                catch (Exception e) {
                    this.plugin.getLogger().log(Level.WARNING, "\u041e\u0448\u0438\u0431\u043a\u0430 \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u043a\u0438 AuthMe LoginEvent: " + e.getMessage(), e);
                }
            }, (Plugin)this.plugin);
            try {
                Class<?> registerEventClass = Class.forName("fr.xephi.authme.events.RegisterEvent");
                Class<? extends Event> regClass = registerEventClass.asSubclass(Event.class);
                Bukkit.getPluginManager().registerEvent(regClass, new Listener() {}, EventPriority.MONITOR, (listener, event) -> {
                    try {
                        Method getPlayerMethod = event.getClass().getMethod("getPlayer", new Class[0]);
                        Player player = (Player)getPlayerMethod.invoke((Object)event, new Object[0]);
                        if (player != null && player.isOnline()) {
                            this.plugin.handlePostLoginCheck(player);
                        }
                    }
                    catch (Exception exception) {
                        // empty catch block
                    }
                }, (Plugin)this.plugin);
            }
            catch (ClassNotFoundException registerEventClass) {
                // empty catch block
            }
            try {
                Class<?> restoreEventClass = Class.forName("fr.xephi.authme.events.RestoreSessionEvent");
                Class<? extends Event> restoreClass = restoreEventClass.asSubclass(Event.class);
                Bukkit.getPluginManager().registerEvent(restoreClass, new Listener() {}, EventPriority.MONITOR, (listener, event) -> {
                    try {
                        Method getPlayerMethod = event.getClass().getMethod("getPlayer", new Class[0]);
                        Player player = (Player)getPlayerMethod.invoke((Object)event, new Object[0]);
                        if (player != null && player.isOnline()) {
                            this.plugin.getLogger().info("AuthMe RestoreSessionEvent \u0437\u0430\u0444\u0438\u043a\u0441\u0438\u0440\u043e\u0432\u0430\u043d \u0434\u043b\u044f " + player.getName() + ", \u0437\u0430\u043f\u0443\u0441\u043a \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0438 2FA...");
                            this.plugin.handlePostLoginCheck(player);
                        }
                    }
                    catch (Exception exception) {
                        // empty catch block
                    }
                }, (Plugin)this.plugin);
            }
            catch (ClassNotFoundException classNotFoundException) {
                // empty catch block
            }
            this.isAuthMeAvailable = true;
            this.plugin.getLogger().info("\u0423\u0441\u043f\u0435\u0448\u043d\u043e \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d \u0445\u0443\u043a AuthMe! 2FA \u0430\u043a\u0442\u0438\u0432\u0438\u0440\u0443\u0435\u0442\u0441\u044f \u0441\u0442\u0440\u043e\u0433\u043e \u043f\u043e\u0441\u043b\u0435 \u0432\u0432\u043e\u0434\u0430 \u043f\u0430\u0440\u043e\u043b\u044f (/login).");
        }
        catch (ClassNotFoundException e) {
            this.plugin.getLogger().warning("\u041a\u043b\u0430\u0441\u0441 \u0441\u043e\u0431\u044b\u0442\u0438\u044f AuthMe \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d: " + e.getMessage());
        }
        catch (Exception e) {
            this.plugin.getLogger().log(Level.WARNING, "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0440\u0435\u0433\u0438\u0441\u0442\u0440\u0438\u0440\u043e\u0432\u0430\u0442\u044c \u0441\u043b\u0443\u0448\u0430\u0442\u0435\u043b\u044c AuthMe: " + e.getMessage(), e);
        }
    }

    public boolean isAuthMeAvailable() {
        return this.isAuthMeAvailable;
    }

    public boolean isAuthenticated(Player player) {
        if (player == null) {
            return false;
        }
        Plugin authMe = Bukkit.getPluginManager().getPlugin("AuthMe");
        if (authMe == null || !authMe.isEnabled()) {
            return true;
        }
        try {
            Class<?> apiClass = Class.forName("fr.xephi.authme.api.v8.AuthMeApi");
            Method getInstance = apiClass.getMethod("getInstance", new Class[0]);
            Object api = getInstance.invoke(null, new Object[0]);
            if (api != null) {
                Method isAuth = apiClass.getMethod("isAuthenticated", Player.class);
                return (Boolean)isAuth.invoke(api, player);
            }
        }
        catch (Throwable throwable) {
            // empty catch block
        }
        return true;
    }
}

