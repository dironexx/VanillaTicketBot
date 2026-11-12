package my.bridge;

import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.minimessage.MiniMessage;

public final class LinkComponents {

    private LinkComponents() {}

    public static Component buildDonateComponent() {
        String msg = "<gradient:#00AAFF:#0055FF>🛒 Официальный магазин доната:</gradient> <white><hover:show_text:'&eКлик: открыть магазин'><click:open_url:'https://vanillaland.store'><u>vanillaland.store</u></click></hover></white>";
        return MiniMessage.miniMessage().deserialize(msg);
    }

    public static Component buildDiscordComponent() {
        String msg = "<gradient:#5865F2:#7289DA>💬 Discord сервера:</gradient> <white><hover:show_text:'&eКлик: присоединиться к Discord'><click:open_url:'https://discord.gg/Ba5cMK7F6a'><u>discord.gg/Ba5cMK7F6a</u></click></hover></white>";
        return MiniMessage.miniMessage().deserialize(msg);
    }

    public static Component buildSiteComponent() {
        String msg = "<gradient:#FFA500:#FF5500>🌐 Наш официальный сайт:</gradient> <white><hover:show_text:'&eКлик: перейти на сайт'><click:open_url:'https://vanillaland.fun'><u>vanillaland.fun</u></click></hover></white>";
        return MiniMessage.miniMessage().deserialize(msg);
    }

    public static Component buildTelegramComponent() {
        String msg = "<gradient:#0088cc:#29b6f6>✈ Наш Telegram канал:</gradient> <white><hover:show_text:'&eКлик: подписаться в Telegram'><click:open_url:'https://t.me/vanilandes'><u>t.me/vanilandes</u></click></hover></white>";
        return MiniMessage.miniMessage().deserialize(msg);
    }

    public static Component buildLinksComponent() {
        String msg = "\n<gradient:#FFA500:#FF7700>✧ ───────────── [ Vanilla Land ] ───────────── ✧</gradient>\n"
            + "<gradient:#00AAFF:#0055FF>🛒 Донат / Магазин:</gradient> <white><hover:show_text:'&eКлик: открыть магазин vanillaland.store'><click:open_url:'https://vanillaland.store'><u>vanillaland.store</u></click></hover></white>\n"
            + "<gradient:#FFA500:#FF5500>🌐 Наш сайт:</gradient> <white><hover:show_text:'&eКлик: перейти на сайт vanillaland.fun'><click:open_url:'https://vanillaland.fun'><u>vanillaland.fun</u></click></hover></white>\n"
            + "<gradient:#5865F2:#7289DA>💬 Discord:</gradient> <white><hover:show_text:'&eКлик: зайти в Discord сервер'><click:open_url:'https://discord.gg/Ba5cMK7F6a'><u>discord.gg/Ba5cMK7F6a</u></click></hover></white>\n"
            + "<gradient:#0088cc:#29b6f6>✈ Telegram:</gradient> <white><hover:show_text:'&eКлик: подписаться в Telegram'><click:open_url:'https://t.me/vanilandes'><u>t.me/vanilandes</u></click></hover></white>\n"
            + "<gradient:#FFA500:#FF7700>✧ ───────────────────────────────────────────── ✧</gradient>\n";
        return MiniMessage.miniMessage().deserialize(msg);
    }
}
