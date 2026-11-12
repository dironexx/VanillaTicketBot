import re
import aiohttp
import shutil
import asyncio
import gc
import json
import logging
import math
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Any

import discord
from discord import app_commands, ui
from discord.ext import commands

from config import Config
from database import DatabaseManager, get_msk_now_str
from design import Colors

logger = logging.getLogger("VanillaBot.Security")

LUCKPERMS_ALERT_CHANNEL_ID = 1550423651122155571




async def ping_http_url(url: str, timeout_sec: float = 2.0) -> str:
    """Реальный замер HTTP доступности и времени ответа веб-ресурса в миллисекундах"""
    if not url:
        return "*Не настроен*"
    t0 = time.perf_counter()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout_sec)) as resp:
                dur = round((time.perf_counter() - t0) * 1000)
                if resp.status == 200:
                    return f"🟢 200 OK `{dur} ms`"
                return f"🟡 {resp.status} `{dur} ms`"
    except asyncio.TimeoutError:
        return "🔴 Таймаут"
    except Exception:
        return "🔴 Недоступен"


async def ping_tcp_port(host: str, port: int, timeout_sec: float = 2.0) -> str:
    """Реальное открытие TCP-сокета для проверки доступности игрового порта снаружи"""
    t0 = time.perf_counter()
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout_sec)
        dur = round((time.perf_counter() - t0) * 1000)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return f"🟢 Открыт `{dur} ms`"
    except asyncio.TimeoutError:
        return "🔴 Таймаут"
    except Exception:
        return "🔴 Недоступен"

def get_bridge_cog(client_or_bot):
    """Надёжно находит ког моста Minecraft по имени класса, атрибуту или ключу"""
    if not client_or_bot:
        return None
    return (
        client_or_bot.get_cog("Мост Minecraft")
        or client_or_bot.get_cog("BridgeCog")
        or client_or_bot.get_cog("MinecraftBridge")
        or next((c for c in getattr(client_or_bot, "cogs", {}).values() if hasattr(c, "active_sockets")), None)
    )

def _admin_role_ids() -> set[int]:
    """ID ролей для security-команд: ADMIN_ROLE_IDS, иначе MOD_ROLE_IDS (без имён ролей)."""
    ids = set(getattr(Config, "ADMIN_ROLE_IDS", []) or [])
    return ids or set(Config.MOD_ROLE_IDS)


def is_tech_admin_or_owner(ctx: commands.Context) -> bool:
    """Проверяет права: владелец сервера, администратор или роль технического администратора (работает в каналах и ЛС)"""
    author = ctx.author
    guild = ctx.guild

    # Если команда вызвана в ЛС — ищем целевую гильдию через бота
    if guild is None and hasattr(ctx.bot, "get_guild") and Config.GUILD_ID:
        guild = ctx.bot.get_guild(Config.GUILD_ID)
        if guild:
            member = guild.get_member(author.id)
            if member:
                author = member

    # Проверка владельца бота
    if hasattr(ctx.bot, "owner_id") and ctx.bot.owner_id and author.id == ctx.bot.owner_id:
        return True
    if hasattr(ctx.bot, "owner_ids") and ctx.bot.owner_ids and author.id in ctx.bot.owner_ids:
        return True

    if not isinstance(author, discord.Member):
        return False

    if guild and author.id == guild.owner_id:
        return True
    if author.guild_permissions.administrator:
        return True

    return any(r.id in _admin_role_ids() for r in author.roles)


_IP_CACHE: dict[str, dict] = {}

async def check_ip_intel(ip: str) -> dict:
    now = time.time()
    # Защита от утечки памяти: очистка кеша при превышении 2000 записей
    if len(_IP_CACHE) > 2000:
        expired = [k for k, v in _IP_CACHE.items() if now - v.get("_cached_at", 0) >= 21600]
        for k in expired:
            _IP_CACHE.pop(k, None)
        if len(_IP_CACHE) > 2000:
            for k in list(_IP_CACHE.keys())[:500]:
                _IP_CACHE.pop(k, None)
    raw = str(ip).strip().lstrip("/")
    if raw.startswith("[") and "]" in raw:
        clean_ip = raw.split("]")[0].lstrip("[").strip()
    elif ":" in raw and "." in raw:
        clean_ip = raw.split(":")[0].strip()
    else:
        clean_ip = raw.strip()
    if not clean_ip or clean_ip.lower() in ("127.0.0.1", "0.0.0.0", "localhost", "::1", "unknown", "none", "n/a", ""):
        return {"is_vpn": False, "country": "Локальный", "city": "", "isp": "Localhost"}

    parts = clean_ip.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        first, second = int(parts[0]), int(parts[1])
        if first == 10 or (first == 172 and 16 <= second <= 31) or (first == 192 and second == 168):
            return {"is_vpn": False, "country": "Локальная сеть", "city": "", "isp": "LAN"}

    now = time.time()
    if clean_ip in _IP_CACHE:
        cached = _IP_CACHE[clean_ip]
        if now - cached.get("_cached_at", 0) < 21600:
            return cached

    timeout = aiohttp.ClientTimeout(total=3.0)

    # 1) HTTPS-провайдер (ipwho.is): IP не уходит в третью сторону открытым текстом
    try:
        url = f"https://ipwho.is/{clean_ip}?security=1"
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    if data.get("success"):
                        security = data.get("security") or {}
                        connection = data.get("connection") or {}
                        is_vpn = bool(security.get("proxy") or security.get("vpn") or security.get("hosting"))
                        if not security:
                            # Бесплатный ipwho.is не отдаёт security — добираем флаги у ip-api
                            try:
                                vpn_timeout = aiohttp.ClientTimeout(total=2.0)
                                async with aiohttp.ClientSession(timeout=vpn_timeout) as vpn_session:
                                    vpn_url = f"http://ip-api.com/json/{clean_ip}?fields=status,proxy,hosting"
                                    async with vpn_session.get(vpn_url) as vpn_resp:
                                        if vpn_resp.status == 200:
                                            vpn_data = await vpn_resp.json()
                                            if vpn_data.get("status") == "success":
                                                is_vpn = bool(vpn_data.get("proxy") or vpn_data.get("hosting"))
                            except Exception as vpn_err:
                                logger.debug(f"VPN fallback error for {clean_ip}: {vpn_err}")
                        res = {
                            "is_vpn": is_vpn,
                            "country": data.get("country") or "",
                            "city": data.get("city") or "",
                            "isp": connection.get("isp") or connection.get("org") or "Неизвестно",
                            "_cached_at": now,
                        }
                        _IP_CACHE[clean_ip] = res
                        return res
    except Exception as e:
        logger.debug(f"ipwho.is error for {clean_ip}: {e}")

    # 2) Фолбэк: ip-api.com (HTTP — только если HTTPS-провайдер недоступен)
    try:
        url = f"http://ip-api.com/json/{clean_ip}?fields=status,country,city,isp,org,proxy,hosting"
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == "success":
                        res = {
                            "is_vpn": bool(data.get("proxy")) or bool(data.get("hosting")),
                            "country": data.get("country", ""),
                            "city": data.get("city", ""),
                            "isp": data.get("isp") or data.get("org") or "Неизвестно",
                            "_cached_at": now,
                        }
                        _IP_CACHE[clean_ip] = res
                        return res
    except Exception as e:
        logger.debug(f"ip-api.com error for {clean_ip}: {e}")

    return {"is_vpn": False, "country": "Не определено", "city": "", "isp": "Не определено"}


class AltsChannelModal(ui.Modal, title="Ввод канала оповещений"):
    def __init__(self, db: Optional[DatabaseManager], panel_view: Optional["AltsPanelControlView"] = None):
        super().__init__()
        self.db = db
        self.panel_view = panel_view
        cur_ch = self.db.get_setting("alts_alert_channel_id", "") if self.db else ""
        self.channel_input = ui.TextInput(
            label="ID канала или ссылка / упоминание",
            default=str(cur_ch) if cur_ch else "",
            placeholder="Например: 1556209087920873542 или #обход-банов",
            required=False,
            max_length=100,
        )
        self.add_item(self.channel_input)

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.channel_input.value.strip()
        # Извлекаем ID из упоминания <#123...>, ссылки или чистых цифр
        match = re.search(r"(\d{17,20})", raw)
        if raw and not match:
            return await interaction.response.send_message(
                "❌ Не удалось распознать ID канала. Укажите ID (17-20 цифр) или упоминание канала.",
                ephemeral=True,
            )

        new_cid = int(match.group(1)) if match else None

        if new_cid:
            # Проверяем доступность канала для бота
            ch = interaction.client.get_channel(new_cid)
            if not ch:
                try:
                    ch = await interaction.client.fetch_channel(new_cid)
                except Exception:
                    ch = None

            if not ch or not hasattr(ch, "send"):
                return await interaction.response.send_message(
                    f"❌ Бот не имеет доступа к каналу с ID `{new_cid}` или этот канал не поддерживает текстовые сообщения.",
                    ephemeral=True,
                )

            guild = getattr(ch, "guild", interaction.guild)
            if guild and guild.me:
                perms = ch.permissions_for(guild.me)
                if not (perms.view_channel and perms.send_messages and perms.embed_links):
                    return await interaction.response.send_message(
                        f"⚠️ У бота нет прав **Просматривать канал**, **Отправлять сообщения** или **Встраивать ссылки** в канале {ch.mention}!\n"
                        f"Пожалуйста, выдайте боту эти права в настройках канала и повторите попытку.",
                        ephemeral=True,
                    )

            if self.db:
                self.db.set_setting("alts_alert_channel_id", str(new_cid))

            # Отправляем тестовый алерт в выбранный канал
            try:
                test_embed = discord.Embed(
                    title="🛡️ Канал оповещений безопасности подключен",
                    description=(
                        f"**Статус:** Канал успешно настроен и проверен.\n"
                        f"**Инициатор:** {interaction.user.mention}\n"
                        f"**Время:** `{get_msk_now_str()}`\n\n"
                        f"*Сюда будут автоматически приходить оповещения об обходе банов, мультиаккаунтах и подозрительных входах.*"
                    ),
                    color=Colors.GREEN,
                    timestamp=datetime.now(timezone.utc),
                )
                test_embed.set_footer(text="Vanilla Land • Безопасность и LiteBans")
                await ch.send(embed=test_embed)
            except Exception as e:
                return await interaction.response.send_message(
                    f"⚠️ Канал сохранён, но не удалось отправить тестовое сообщение: `{e}`",
                    ephemeral=True,
                )

            if self.panel_view:
                self.panel_view._sync_buttons()
                try:
                    if interaction.message:
                        await interaction.message.edit(embed=self.panel_view.get_embed(), view=self.panel_view)
                except Exception:
                    pass

            await interaction.response.send_message(
                f"✅ Канал оповещений безопасности успешно установлен на {ch.mention} (`{new_cid}`)!\n"
                f"Тестовое сообщение доставлено в канал.",
                ephemeral=True,
            )
        else:
            if self.db:
                self.db.set_setting("alts_alert_channel_id", "")
            if self.panel_view:
                self.panel_view._sync_buttons()
                try:
                    if interaction.message:
                        await interaction.message.edit(embed=self.panel_view.get_embed(), view=self.panel_view)
                except Exception:
                    pass
            await interaction.response.send_message(
                "🔄 Канал оповещений сброшен на значение по умолчанию (автоопределение из системных логов).",
                ephemeral=True,
            )


class AltsQuickWhoisModal(ui.Modal, title="Быстрый поиск аккаунтов (Whois)"):
    def __init__(self, db: Optional[DatabaseManager], bot: Optional[commands.Bot] = None):
        super().__init__()
        self.db = db
        self.bot = bot
        self.query_input = ui.TextInput(
            label="Ник игрока или IP-адрес",
            placeholder="Например: Steve или 194.25.110.197",
            required=True,
            max_length=64,
        )
        self.add_item(self.query_input)

    async def on_submit(self, interaction: discord.Interaction):
        query = self.query_input.value.strip()
        if not self.db:
            return await interaction.response.send_message("❌ База данных не подключена.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        effective_bot = self.bot or interaction.client
        bridge_cog = get_bridge_cog(effective_bot)
        online_players = getattr(bridge_cog, "mc_players", []) if bridge_cog else []
        online_set = {p.lower() for p in online_players}

        show_2fa = (self.db.get_setting("whois_show_2fa", "true").lower() == "true") if self.db else True
        show_net = (self.db.get_setting("whois_show_net", "true").lower() == "true") if self.db else True
        show_geo = (self.db.get_setting("whois_show_geo", "true").lower() == "true") if self.db else True
        show_alts = (self.db.get_setting("whois_show_alts", "true").lower() == "true") if self.db else True
        show_litebans = (self.db.get_setting("whois_show_litebans", "true").lower() == "true") if self.db else True

        is_ip = bool(re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", query))
        if is_ip:
            alts_raw = self.db.get_alts_by_ip(query)
            intel = await check_ip_intel(query)
            embed = discord.Embed(
                title=f"🌐 Досье IP • {query}",
                color=Colors.DARK,
                timestamp=datetime.now(timezone.utc),
            )
            if intel and (show_net or show_geo):
                net_lines = []
                if show_geo:
                    country = intel.get("country", "")
                    city = intel.get("city", "")
                    loc = f"{country}, {city}".strip(", ") or "Не определена"
                    net_lines.append(f"• **Локация:** {loc}")
                if show_net:
                    if intel.get("is_vpn"):
                        net_type = "VPN обнаружен"
                    else:
                        isp = intel.get("isp", "").strip()
                        isp_clean = isp if isp and isp != "Неизвестно" else "Обычный провайдер"
                        net_type = f"Провайдер — {isp_clean}"
                    net_lines.append(f"• **Тип сети:** `{net_type}`")
                embed.add_field(name="Сетевые данные", value="\n".join(net_lines), inline=False)

            if show_alts:
                if alts_raw:
                    lines = []
                    for a in alts_raw:
                        p = a.get("player_name", "Unknown")
                        on_tag = "`[Онлайн]`" if p.lower() in online_set else "`[Оффлайн]`"
                        lines.append(f"• `{p}` — {on_tag}")
                    embed.add_field(name=f"Аккаунты на этом IP ({len(alts_raw)})", value="\n".join(lines[:20]), inline=False)
                else:
                    embed.add_field(name="Связанные аккаунты", value="*В локальной базе бота нет записей об этом IP.*", inline=False)

            embed.set_footer(text="Vanilla Land • Security Intelligence")
            return await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            alts_data = self.db.get_player_alts(query)
            alts = alts_data.get("alts", [])
            ips = self.db.get_player_ips(query, limit=5)
            on_tag = "`[Онлайн]`" if query.lower() in online_set else "`[Оффлайн]`"

            embed = discord.Embed(
                title=f"👤 Досье игрока • {query} {on_tag}",
                color=Colors.DARK,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url=f"https://mc-heads.net/avatar/{query}/128.png")

            # 2FA & Discord link section
            if show_2fa:
                linked = self.db.get_linked_account_by_mc(query) if self.db else None
                sec_lines = []
                if linked:
                    is_2fa = linked.get("two_factor_enabled", False)
                    trust_h = linked.get("trust_duration_hours", 48)
                    status_2fa = f"Включен (сессия = {trust_h} ч.)" if is_2fa else "Выключен"
                    dc_user = f"<@{linked['discord_user_id']}> (`{linked['discord_user_id']}`)"
                    sec_lines.append(f"• 🔐 **2FA - Google Authenticator:** `{status_2fa}`")
                    sec_lines.append(f"• 🔗 **Привязка Discord:** {dc_user}")
                else:
                    sec_lines.append("• 🔐 **2FA - Google Authenticator:** `Не настроен`")
                    sec_lines.append("• 🔗 **Привязка Discord:** `Не привязан`")
                embed.add_field(name="Безопасность", value="\n".join(sec_lines), inline=False)

            # Network & IP section
            if ips and (show_net or show_geo):
                latest_ip = ips[0].get("ip", "")
                intel = await check_ip_intel(latest_ip) if latest_ip else None
                net_lines = [f"• **Текущий IP:** `{latest_ip}`"]
                if intel:
                    if show_geo:
                        country = intel.get("country", "")
                        city = intel.get("city", "")
                        loc = f"{country}, {city}".strip(", ") or "Не определена"
                        net_lines.append(f"• **Локация:** {loc}")
                    if show_net:
                        if intel.get("is_vpn"):
                            net_type = "VPN обнаружен"
                        else:
                            isp = intel.get("isp", "").strip()
                            isp_clean = isp if isp and isp != "Неизвестно" else "Обычный провайдер"
                            net_type = f"Провайдер — {isp_clean}"
                        net_lines.append(f"• **Тип сети:** `{net_type}`")
                embed.add_field(name="Сетевые данные", value="\n".join(net_lines), inline=False)

            # Alts section
            if show_alts:
                if alts:
                    alt_lines = []
                    for a in alts:
                        aname = a.get("player_name", "Unknown")
                        a_on = "`[Онлайн]`" if aname.lower() in online_set else "`[Оффлайн]`"
                        alt_lines.append(f"• `{aname}` — {a_on}")
                    embed.add_field(name=f"Связанные аккаунты ({len(alts)})", value="\n".join(alt_lines[:20]), inline=False)
                else:
                    embed.add_field(name="Связанные аккаунты", value="*Других аккаунтов на известных IP не обнаружено.*", inline=False)



            embed.set_footer(text="Vanilla Land • Security Intelligence")
            return await interaction.followup.send(embed=embed, ephemeral=True)



class AltsChannelConfigView(ui.View):
    """Интерактивное меню выбора и тестирования канала алертов об обходе банов"""

    def __init__(self, db: Optional[DatabaseManager], bot: commands.Bot, panel_view: Optional["AltsPanelControlView"] = None):
        super().__init__(timeout=180)
        self.db = db
        self.bot = bot
        self.panel_view = panel_view

    @ui.select(
        cls=ui.ChannelSelect,
        channel_types=[discord.ChannelType.text, discord.ChannelType.news],
        placeholder="Выберите канал для алертов из списка сервера...",
        min_values=1,
        max_values=1,
        row=0,
    )
    async def select_channel(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        selected_ch = select.values[0]
        ch = selected_ch
        if not hasattr(ch, "send"):
            resolved = self.bot.get_channel(selected_ch.id)
            if resolved:
                ch = resolved

        guild = getattr(ch, "guild", interaction.guild)
        if guild and guild.me and hasattr(ch, "permissions_for"):
            perms = ch.permissions_for(guild.me)
            if not (perms.view_channel and perms.send_messages and perms.embed_links):
                return await interaction.response.send_message(
                    f"⚠️ У бота нет прав **Просматривать канал**, **Отправлять сообщения** или **Встраивать ссылки** в канале {ch.mention}!\n"
                    f"Выдайте боту права и попробуйте снова.",
                    ephemeral=True,
                )

        if self.db:
            self.db.set_setting("alts_alert_channel_id", str(ch.id))

        try:
            test_embed = discord.Embed(
                title="🛡️ Канал оповещений безопасности подключен",
                description=(
                    f"**Статус:** Канал успешно настроен и проверен.\n"
                    f"**Инициатор:** {interaction.user.mention}\n"
                    f"**Время:** `{get_msk_now_str()}`\n\n"
                    f"*Сюда будут автоматически приходить оповещения об обходе банов, мультиаккаунтах и подозрительных входах.*"
                ),
                color=Colors.GREEN,
                timestamp=datetime.now(timezone.utc),
            )
            test_embed.set_footer(text="Vanilla Land • Безопасность и LiteBans")
            await ch.send(embed=test_embed)
            test_status = "Тестовое сообщение успешно доставлено."
        except Exception as e:
            test_status = f"Канал сохранён, но при тесте возникла ошибка: `{e}`"

        if self.panel_view:
            self.panel_view._sync_buttons()

        await interaction.response.send_message(
            f"✅ Канал оповещений об обходе банов установлен на {ch.mention} (`{ch.id}`)!\n{test_status}",
            ephemeral=True,
        )

    @ui.button(label="Тестовый алерт", style=discord.ButtonStyle.success, emoji="🔔", row=1)
    async def btn_test_alert(self, interaction: discord.Interaction, button: ui.Button):
        sec_cog = interaction.client.get_cog("SecurityCog")
        target_ch = await sec_cog._get_alert_channel() if sec_cog else None

        if not target_ch:
            return await interaction.response.send_message(
                "❌ Не удалось определить канал для отправки алертов! Проверьте настройки каналов или выберите канал в меню выше.",
                ephemeral=True,
            )

        try:
            test_embed = discord.Embed(
                title="🛡️ Тест канала алертов безопасности",
                description=(
                    f"**Статус:** Канал проверен и полностью готов к работе!\n"
                    f"**Канал доставки:** {target_ch.mention} (`{getattr(target_ch, 'id', 'N/A')}`)\n"
                    f"**Проверил:** {interaction.user.mention}\n"
                    f"**Время:** `{get_msk_now_str()}`\n\n"
                    f"*Это тестовое уведомление подтверждает, что бот имеет все необходимые права (View Channel, Send Messages, Embed Links).* "
                ),
                color=Colors.BLUE,
                timestamp=datetime.now(timezone.utc),
            )
            test_embed.set_footer(text="Vanilla Land • LiteBans Guard Test")
            await target_ch.send(embed=test_embed)
            await interaction.response.send_message(
                f"✅ Тестовый алерт успешно доставлен в {target_ch.mention}!",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Ошибка отправки в {target_ch.mention}: `{e}`\n"
                f"Убедитесь, что у роли бота есть права **Просматривать канал**, **Отправлять сообщения** и **Встраивать ссылки**.",
                ephemeral=True,
            )

    @ui.button(label="Ввести ID вручную", style=discord.ButtonStyle.secondary, emoji="⌨️", row=1)
    async def btn_manual_id(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(AltsChannelModal(self.db, self.panel_view))

    @ui.button(label="Сбросить по умолчанию", style=discord.ButtonStyle.danger, emoji="🔄", row=1)
    async def btn_reset(self, interaction: discord.Interaction, button: ui.Button):
        if self.db:
            self.db.set_setting("alts_alert_channel_id", "")
        if self.panel_view:
            self.panel_view._sync_buttons()
        await interaction.response.send_message(
            "🔄 Канал оповещений сброшен на системный канал по умолчанию.",
            ephemeral=True,
        )


class AltsWhitelistModal(ui.Modal, title="Добавить в белый список"):
    def __init__(self, db: Optional[DatabaseManager], whitelist_view: Optional["AltsWhitelistView"] = None):
        super().__init__()
        self.db = db
        self.whitelist_view = whitelist_view

        self.target_input = ui.TextInput(
            label="Никнейм игрока или IP адрес",
            placeholder="Например: Player123 или 94.25.110.197",
            required=True,
            max_length=64,
        )
        self.reason_input = ui.TextInput(
            label="Причина добавления в исключения",
            placeholder="Например: Братья играют с одного роутера / Тестер",
            required=False,
            max_length=128,
        )
        self.add_item(self.target_input)
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        target = self.target_input.value.strip()
        reason = self.reason_input.value.strip() or "Исключение безопасности"
        if not target:
            return await interaction.response.send_message("❌ Укажите ник или IP.", ephemeral=True)

        is_ip = bool(re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", target))
        target_type = "ip" if is_ip else "player"

        if self.db and hasattr(self.db, "add_security_whitelist"):
            self.db.add_security_whitelist(
                target=target,
                target_type=target_type,
                reason=reason,
                added_by=interaction.user.name,
            )

        if self.whitelist_view:
            await interaction.response.defer()
            await self.whitelist_view.refresh(interaction)
        else:
            await interaction.response.send_message(
                f"✅ **{target}** ({target_type}) успешно добавлен в белый список!\n**Причина:** {reason}",
                ephemeral=True,
            )


class AltsWhitelistDeleteSelect(ui.Select):
    def __init__(self, items: list[dict]):
        options = []
        for it in items[:25]:
            t = it["target"]
            typ = it.get("type", "player")
            reason = it.get("reason", "") or "Без причины"
            label = f"{t} ({typ})"[:100]
            desc = f"Причина: {reason}"[:100]
            options.append(discord.SelectOption(label=label, value=t, description=desc, emoji="🗑️"))
        super().__init__(
            placeholder="Выберите запись для удаления из исключений...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        target = self.values[0]
        view: "AltsWhitelistView" = self.view
        if view.db and hasattr(view.db, "remove_security_whitelist"):
            view.db.remove_security_whitelist(target)
        await view.refresh(interaction)


class AltsWhitelistView(ui.View):
    def __init__(self, db: Optional[DatabaseManager], bot: commands.Bot, panel_view: Optional["AltsPanelControlView"] = None):
        super().__init__(timeout=180)
        self.db = db
        self.bot = bot
        self.panel_view = panel_view
        self._populate_items()

    def _populate_items(self):
        self.clear_items()
        items = self.db.get_security_whitelist() if self.db else []
        if items:
            self.add_item(AltsWhitelistDeleteSelect(items))
        self.add_item(self.btn_add_entry)
        self.add_item(self.btn_refresh)
        if items:
            self.add_item(self.btn_clear_all)

    def get_embed(self) -> discord.Embed:
        wl = self.db.get_security_whitelist() if self.db else []
        if not wl:
            desc = "*Белый список пуст. Вы можете добавить ник игрока или IP в исключения с помощью кнопки ниже.*"
        else:
            wl_lines = [
                f"• `{w['target']}` ({w['type']}) — *{w['reason'] or 'Без причины'}* (добавил: {w['added_by']}, {w.get('added_at', '')[:10]})"
                for w in wl[:25]
            ]
            desc = f"**Всего исключений в базе:** {len(wl)}\n\n" + "\n".join(wl_lines)

        embed = discord.Embed(
            title="🛡️ Белый список исключений безопасности",
            description=desc + "\n\n*Игроки и IP из этого списка игнорируются автокиком и автобаном при мультиаккаунтах и проверках.*",
            color=Colors.BLUE,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Vanilla Land • Общая база данных безопасности")
        return embed

    @ui.button(label="Добавить исключение", style=discord.ButtonStyle.success, emoji="➕", row=1)
    async def btn_add_entry(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(AltsWhitelistModal(self.db, self))

    @ui.button(label="Обновить", style=discord.ButtonStyle.secondary, emoji="🔄", row=1)
    async def btn_refresh(self, interaction: discord.Interaction, button: ui.Button):
        await self.refresh(interaction)

    @ui.button(label="Очистить всё", style=discord.ButtonStyle.danger, emoji="🧹", row=1)
    async def btn_clear_all(self, interaction: discord.Interaction, button: ui.Button):
        if not self.db:
            return await interaction.response.send_message("База данных недоступна.", ephemeral=True)
        await interaction.response.send_message(
            "Удалить **все** исключения безопасности? Это действие необратимо.",
            view=WhitelistClearConfirmView(self),
            ephemeral=True,
        )

    async def refresh(self, interaction: discord.Interaction):
        self._populate_items()
        embed = self.get_embed()
        if interaction.response.is_done():
            await interaction.followup.edit_message(message_id=interaction.message.id, embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)


class WhitelistClearConfirmView(ui.View):
    def __init__(self, owner_view: "AltsWhitelistView"):
        super().__init__(timeout=60)
        self.owner_view = owner_view

    @ui.button(label="Да, удалить всё", style=discord.ButtonStyle.danger, emoji="🧹")
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        db = self.owner_view.db
        if db:
            with db._get_connection() as conn:
                conn.execute("DELETE FROM security_whitelist")
                conn.commit()
        await interaction.response.edit_message(
            content="Белый список исключений очищен.", embed=None, view=None
        )


class AltsDisplaySettingsView(ui.View):
    """Интерфейс настройки отображения полей в карточках досье (Whois)"""
    def __init__(self, db: Optional[DatabaseManager], panel_view: Optional["AltsPanelControlView"] = None):
        super().__init__(timeout=180)
        self.db = db
        self.panel_view = panel_view
        self._sync_buttons()

    def _sync_buttons(self):
        s_2fa = (self.db.get_setting("whois_show_2fa", "true").lower() == "true") if self.db else True
        s_net = (self.db.get_setting("whois_show_net", "true").lower() == "true") if self.db else True
        s_geo = (self.db.get_setting("whois_show_geo", "true").lower() == "true") if self.db else True
        s_alts = (self.db.get_setting("whois_show_alts", "true").lower() == "true") if self.db else True

        self.btn_toggle_2fa.label = f"2FA и Discord: {'ВКЛ' if s_2fa else 'ВЫКЛ'}"
        self.btn_toggle_2fa.style = discord.ButtonStyle.success if s_2fa else discord.ButtonStyle.secondary

        self.btn_toggle_net.label = f"Тип сети: {'ВКЛ' if s_net else 'ВЫКЛ'}"
        self.btn_toggle_net.style = discord.ButtonStyle.success if s_net else discord.ButtonStyle.secondary

        self.btn_toggle_geo.label = f"Геолокация: {'ВКЛ' if s_geo else 'ВЫКЛ'}"
        self.btn_toggle_geo.style = discord.ButtonStyle.success if s_geo else discord.ButtonStyle.secondary

        self.btn_toggle_alts.label = f"Связанные акк: {'ВКЛ' if s_alts else 'ВЫКЛ'}"
        self.btn_toggle_alts.style = discord.ButtonStyle.success if s_alts else discord.ButtonStyle.secondary

    def get_embed(self) -> discord.Embed:
        s_2fa = (self.db.get_setting("whois_show_2fa", "true").lower() == "true") if self.db else True
        s_net = (self.db.get_setting("whois_show_net", "true").lower() == "true") if self.db else True
        s_geo = (self.db.get_setting("whois_show_geo", "true").lower() == "true") if self.db else True
        s_alts = (self.db.get_setting("whois_show_alts", "true").lower() == "true") if self.db else True

        desc = (
            "**Настройка отображения карточек (Whois / Досье):**\n\n"
            f"🔐 **2FA и привязка Discord:** `{'Показывается' if s_2fa else 'Скрыто'}`\n"
            f"🌐 **Тип сети (VPN / Провайдер):** `{'Показывается' if s_net else 'Скрыто'}`\n"
            f"📍 **Геолокация (Страна, город):** `{'Показывается' if s_geo else 'Скрыто'}`\n"
            f"👥 **Связанные аккаунты (Твинки):** `{'Показывается' if s_alts else 'Скрыто'}`\n\n"
            "*Нажмите на кнопку ниже, чтобы включить или скрыть нужный блок в карточках досье игроков.*"
        )
        embed = discord.Embed(
            title="⚙️ Конфигурация отображения досье",
            description=desc,
            color=Colors.DARK,
        )
        embed.set_footer(text="Vanilla Land • Display Customization")
        return embed

    @ui.button(label="2FA и Discord: ВКЛ", style=discord.ButtonStyle.success, row=0)
    async def btn_toggle_2fa(self, interaction: discord.Interaction, button: ui.Button):
        cur = (self.db.get_setting("whois_show_2fa", "true").lower() == "true") if self.db else True
        if self.db:
            self.db.set_setting("whois_show_2fa", "false" if cur else "true")
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @ui.button(label="Тип сети: ВКЛ", style=discord.ButtonStyle.success, row=0)
    async def btn_toggle_net(self, interaction: discord.Interaction, button: ui.Button):
        cur = (self.db.get_setting("whois_show_net", "true").lower() == "true") if self.db else True
        if self.db:
            self.db.set_setting("whois_show_net", "false" if cur else "true")
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @ui.button(label="Геолокация: ВКЛ", style=discord.ButtonStyle.success, row=1)
    async def btn_toggle_geo(self, interaction: discord.Interaction, button: ui.Button):
        cur = (self.db.get_setting("whois_show_geo", "true").lower() == "true") if self.db else True
        if self.db:
            self.db.set_setting("whois_show_geo", "false" if cur else "true")
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @ui.button(label="Связанные акк: ВКЛ", style=discord.ButtonStyle.success, row=1)
    async def btn_toggle_alts(self, interaction: discord.Interaction, button: ui.Button):
        cur = (self.db.get_setting("whois_show_alts", "true").lower() == "true") if self.db else True
        if self.db:
            self.db.set_setting("whois_show_alts", "false" if cur else "true")
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)


class AltsPanelControlView(ui.View):

    """Интерактивная панель управления защитой от твинков, обхода банов и мультиаккаунтов"""
    def __init__(self, db: Optional[DatabaseManager], bot: commands.Bot):
        super().__init__(timeout=None)
        self.db = db
        self.bot = bot
        self._sync_buttons()

    def _check_perms(self, member: discord.Member) -> bool:
        return bool(member.guild_permissions.administrator) or any(
            r.id in _admin_role_ids() for r in member.roles
        )

    def _sync_buttons(self):
        mode = self.db.get_setting("alts_protection_mode", "alert").lower() if self.db else "alert"
        max_ip = self.db.get_setting("alts_max_per_ip", "2") if self.db else "2"
        vpn = (self.db.get_setting("alts_vpn_check", "true").lower() == "true") if self.db else True
        only_bans = (self.db.get_setting("alts_alert_only_bans", "true").lower() == "true") if self.db else True

        if mode == "autoban":
            self.btn_mode.label = "Режим: Авто-бан"
            self.btn_mode.style = discord.ButtonStyle.danger
        elif mode == "autokick":
            self.btn_mode.label = "Режим: Авто-кик"
            self.btn_mode.style = discord.ButtonStyle.secondary
        else:
            self.btn_mode.label = "Режим: Алерт"
            self.btn_mode.style = discord.ButtonStyle.primary

        self.btn_only_bans.label = f"Алерты: {'Только баны' if only_bans else 'Все твинки'}"
        self.btn_only_bans.style = discord.ButtonStyle.success if only_bans else discord.ButtonStyle.secondary

        self.btn_max_ip.label = f"Лимит IP: {max_ip}"
        self.btn_max_ip.style = discord.ButtonStyle.secondary

        self.btn_vpn.label = f"VPN чек: {'ВКЛ' if vpn else 'ВЫКЛ'}"
        self.btn_vpn.style = discord.ButtonStyle.success if vpn else discord.ButtonStyle.secondary

    def get_embed(self) -> discord.Embed:
        mode = self.db.get_setting("alts_protection_mode", "alert").lower() if self.db else "alert"
        max_ip = self.db.get_setting("alts_max_per_ip", "2") if self.db else "2"
        vpn = (self.db.get_setting("alts_vpn_check", "true").lower() == "true") if self.db else True
        only_bans = (self.db.get_setting("alts_alert_only_bans", "true").lower() == "true") if self.db else True
        ch_id = self.db.get_setting("alts_alert_channel_id") if self.db else None
        ch_str = f"<#{ch_id}> (`{ch_id}`)" if ch_id and ch_id.isdigit() else "*автоопределение (системный канал)*"

        stats = self.db.get_db_stats() if self.db and hasattr(self.db, "get_db_stats") else {}
        tracked_ips = stats.get("tracked_ips", 0)
        tracked_players = stats.get("tracked_players", 0)

        bridge_cog = get_bridge_cog(self.bot)
        online_count = len(getattr(bridge_cog, "mc_players", [])) if bridge_cog else 0

        wl_count = len(self.db.get_security_whitelist()) if self.db and hasattr(self.db, "get_security_whitelist") else 0
        inc_count = len(self.db.get_security_incidents(100)) if self.db and hasattr(self.db, "get_security_incidents") else 0

        mode_desc_map = {
            "alert": "Оповещение (alert) — подробный алерт с кнопками в Discord",
            "autokick": "Авто-кик (autokick) — мгновенный кик с сервера с причиной бана твинка",
            "autoban": "Авто-бан (autoban) — перманентный бан через LiteBans за обход",
        }
        mode_desc = mode_desc_map.get(mode, "Оповещение (alert)")

        desc = (
            "**Текущие параметры защиты:**\n\n"
            f"🎯 **Механизм детекта:** `Точный IP адрес`\n"
            f"⚙️ **Режим реакции:** `{mode_desc}`\n"
            f"📢 **Фильтрация алертов:** `{'Только при наличии бана' if only_bans else 'Все совпадения IP'}`\n"
            f"👥 **Лимит одновременных входов:** `{max_ip} акк. с одного IP`\n"
            f"🌐 **Проверка VPN / Прокси:** `{'Включена' if vpn else 'Выключена'}`\n"
            f"📢 **Канал оповещений:** {ch_str}\n\n"
            "**Сводка базы данных и LiteBans:**\n"
            f"🔗 **LiteBans:** `Прямая сверка ({'{history}'} и {'{bans}'})`\n"
            f"💾 **Уникальных IP в базе:** `{tracked_ips}`\n"
            f"👤 **Игроков под наблюдением:** `{tracked_players}`\n"
            f"🟢 **Текущий онлайн Minecraft:** `{online_count}`\n"
            f"🛡️ **Исключений в белом списке:** `{wl_count}`\n"
            f"📜 **Зафиксировано инцидентов:** `{inc_count}`\n\n"
            "*Все оповещения содержат настоящую причину из LiteBans, ник забаненного аккаунта, срок и кнопки действий для модерации.*"
        )

        embed = discord.Embed(
            title="🛡️ Управление безопасностью • Защита от твинков и обхода банов",
            description=desc,
            color=Colors.DARK,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Vanilla Land • Центр безопасности LiteBans Guard")
        return embed

    @ui.button(label="Режим: Алерт", style=discord.ButtonStyle.primary, custom_id="btn_alts_mode", row=0)
    async def btn_mode(self, interaction: discord.Interaction, button: ui.Button):
        if not isinstance(interaction.user, discord.Member) or not self._check_perms(interaction.user):
            return await interaction.response.send_message("❌ Недостаточно прав.", ephemeral=True)
        cur = self.db.get_setting("alts_protection_mode", "alert").lower() if self.db else "alert"
        next_mode = {"alert": "autokick", "autokick": "autoban", "autoban": "alert"}.get(cur, "alert")
        if self.db:
            self.db.set_setting("alts_protection_mode", next_mode)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @ui.button(label="Алерты: Только баны", style=discord.ButtonStyle.success, custom_id="btn_alts_only_bans", row=0)
    async def btn_only_bans(self, interaction: discord.Interaction, button: ui.Button):
        if not isinstance(interaction.user, discord.Member) or not self._check_perms(interaction.user):
            return await interaction.response.send_message("❌ Недостаточно прав.", ephemeral=True)
        cur = (self.db.get_setting("alts_alert_only_bans", "true").lower() == "true") if self.db else True
        if self.db:
            self.db.set_setting("alts_alert_only_bans", "false" if cur else "true")
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @ui.button(label="Лимит IP: 2", style=discord.ButtonStyle.secondary, custom_id="btn_alts_max_ip", row=0)
    async def btn_max_ip(self, interaction: discord.Interaction, button: ui.Button):
        if not isinstance(interaction.user, discord.Member) or not self._check_perms(interaction.user):
            return await interaction.response.send_message("❌ Недостаточно прав.", ephemeral=True)
        cur = int(self.db.get_setting("alts_max_per_ip", "2") or 2) if self.db else 2
        next_map = {1: 2, 2: 3, 3: 4, 4: 5, 5: 1}
        new_val = next_map.get(cur, 2)
        if self.db:
            self.db.set_setting("alts_max_per_ip", str(new_val))
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @ui.button(label="VPN чек: ВКЛ", style=discord.ButtonStyle.success, custom_id="btn_alts_vpn", row=1)
    async def btn_vpn(self, interaction: discord.Interaction, button: ui.Button):
        if not isinstance(interaction.user, discord.Member) or not self._check_perms(interaction.user):
            return await interaction.response.send_message("❌ Недостаточно прав.", ephemeral=True)
        cur = (self.db.get_setting("alts_vpn_check", "true").lower() == "true") if self.db else True
        if self.db:
            self.db.set_setting("alts_vpn_check", "false" if cur else "true")
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @ui.button(label="Настроить канал", style=discord.ButtonStyle.primary, emoji="📢", custom_id="btn_alts_channel", row=1)
    async def btn_channel(self, interaction: discord.Interaction, button: ui.Button):
        if not isinstance(interaction.user, discord.Member) or not self._check_perms(interaction.user):
            return await interaction.response.send_message("❌ Недостаточно прав.", ephemeral=True)
        view = AltsChannelConfigView(self.db, self.bot, self)
        cur_id = self.db.get_setting("alts_alert_channel_id", "") if self.db else ""
        ch_text = f"<#{cur_id}> (`{cur_id}`)" if cur_id and cur_id.isdigit() else "*автоопределение из системных логов*"
        desc_ch = (
            f"**Текущий канал:** {ch_text}\n\n"
            "• **Выберите канал** в выпадающем списке ниже\n"
            "• Нажмите **«Тестовый алерт»**, чтобы проверить доставку\n"
            "• Нажмите **«Ввести ID вручную»** для ввода точного ID\n"
            "• Нажмите **«Сбросить по умолчанию»** для отмены кастомного канала"
        )
        embed = discord.Embed(
            title="📢 Настройка канала оповещений об обходе банов",
            description=desc_ch,
            color=Colors.BLUE,
        )
        embed.set_footer(text="Vanilla Land • Безопасность и LiteBans")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @ui.button(label="Whois (Поиск)", style=discord.ButtonStyle.secondary, emoji="🔎", custom_id="btn_alts_whois", row=1)
    async def btn_quick_whois(self, interaction: discord.Interaction, button: ui.Button):
        if not isinstance(interaction.user, discord.Member) or not self._check_perms(interaction.user):
            return await interaction.response.send_message("❌ Недостаточно прав.", ephemeral=True)
        await interaction.response.send_modal(AltsQuickWhoisModal(self.db, self.bot))

    @ui.button(label="Вид карточек", style=discord.ButtonStyle.secondary, emoji="⚙️", custom_id="btn_alts_card_settings", row=1)
    async def btn_card_settings(self, interaction: discord.Interaction, button: ui.Button):
        if not isinstance(interaction.user, discord.Member) or not self._check_perms(interaction.user):
            return await interaction.response.send_message("❌ Недостаточно прав.", ephemeral=True)
        view = AltsDisplaySettingsView(self.db, self)
        await interaction.response.send_message(embed=view.get_embed(), view=view, ephemeral=True)

    @ui.button(label="Сканировать онлайн", style=discord.ButtonStyle.primary, emoji="🔍", custom_id="btn_alts_scan_online", row=2)
    async def btn_scan_online(self, interaction: discord.Interaction, button: ui.Button):
        if not isinstance(interaction.user, discord.Member) or not self._check_perms(interaction.user):
            return await interaction.response.send_message("❌ Недостаточно прав.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        bridge_cog = get_bridge_cog(self.bot)
        online_players = list(getattr(bridge_cog, "mc_players", [])) if bridge_cog else []

        bridge_data = None
        is_conn = False
        if bridge_cog and hasattr(bridge_cog, "broadcast_packet"):
            if hasattr(bridge_cog, "is_connected"):
                is_conn = bool(bridge_cog.is_connected)
            elif hasattr(bridge_cog, "active_sockets"):
                is_conn = len(bridge_cog.active_sockets) > 0
            else:
                is_conn = True

        if is_conn:
            try:
                await bridge_cog.broadcast_packet({"type": "scan_online_bans"})
                def check_resp(p_type, d):
                    return p_type == "scan_online_bans_result"
                _, bridge_data = await self.bot.wait_for("bridge_packet", check=check_resp, timeout=4.0)
            except Exception:
                bridge_data = None

        if bridge_data:
            total_online = bridge_data.get("total_online", len(online_players))
            players = bridge_data.get("players", [])
            lines = [f"🔍 **Результаты онлайн-проверки банов LiteBans ({total_online} игроков онлайн):**\n"]
            banned_evasion_count = 0
            alts_clean_count = 0

            for p_info in players:
                p_name = p_info.get("player", "Игрок")
                p_ip = p_info.get("ip", "Не определён")
                banned_alts = p_info.get("banned_alts", [])
                clean_alts = p_info.get("clean_alts", [])

                if banned_alts:
                    banned_evasion_count += 1
                    lines.append(f"🚨 **`{p_name}`** (IP: `{p_ip}`): **ОБХОД БАНА!**")
                    for b in banned_alts:
                        b_nick = b.get("player", "Твинк")
                        b_reason = b.get("reason", "Нарушение правил")
                        b_dur = b.get("duration", "Навсегда")
                        b_by = b.get("banned_by", "Console")
                        lines.append(f"  └ ⛔ Забаненный твинк: **`{b_nick}`** — *{b_reason}* (срок: {b_dur}, выдал: {b_by})")
                elif clean_alts:
                    alts_clean_count += 1
                    lines.append(f"• **`{p_name}`** (IP: `{p_ip}`): твинки ({len(clean_alts)}) — {', '.join(f'`{n}`' for n in clean_alts[:5])}")

            if banned_evasion_count == 0 and alts_clean_count == 0:
                lines.append(f"✅ Все онлайн-игроки ({total_online}) чисты: активных банов в LiteBans и совпадений по IP не обнаружено.")
            else:
                summary = []
                if banned_evasion_count > 0:
                    summary.append(f"🚨 Игроков с забаненными твинками: **{banned_evasion_count}**")
                if alts_clean_count > 0:
                    summary.append(f"👥 Игроков с чистыми твинками: **{alts_clean_count}**")
                lines.append("\n" + " | ".join(summary))

            embed_color = Colors.RED if banned_evasion_count > 0 else (Colors.GOLD if alts_clean_count > 0 else Colors.GREEN)
            embed = discord.Embed(
                title="🛡️ Экспресс-сканирование онлайна и банов LiteBans",
                description="\n".join(lines[:25]),
                color=embed_color,
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_footer(text="Vanilla Land • LiteBans Live Scan")
            return await interaction.followup.send(embed=embed, ephemeral=True)

        # Fallback to local DB scan if bridge not responding
        if not online_players:
            return await interaction.followup.send("ℹ️ На сервере сейчас нет онлайн игроков для проверки.", ephemeral=True)

        lines = [f"🔍 **Результаты сканирования онлайна ({len(online_players)} игроков):**\n"]
        flagged_count = 0
        sec_cog = self.bot.get_cog("SecurityCog")
        active_ips = getattr(sec_cog, "active_player_ips", {}) if sec_cog else {}

        for p in online_players:
            alts_info = self.db.get_player_alts(p) if self.db else {}
            alts = alts_info.get("alts", [])
            alt_names = [a.get("player_name", "") for a in alts if a.get("player_name", "").lower() != p.lower()]
            p_ip = active_ips.get(p.lower()) or alts_info.get("current_ip", "")
            if not p_ip and self.db:
                with self.db._get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT ip FROM player_ips WHERE lower(player_name)=lower(?) ORDER BY last_seen DESC LIMIT 1", (p,))
                    row = cur.fetchone()
                    if row:
                        p_ip = row[0]

            if not p_ip:
                p_ip = "Не зафиксирован"

            if alt_names:
                lines.append(f"• **`{p}`** (IP: `{p_ip}`): твинки ({len(alt_names)}) — {', '.join(f'`{n}`' for n in alt_names[:5])}")
                flagged_count += 1

        if flagged_count == 0:
            lines.append("✅ Ни у одного из онлайн-игроков не обнаружено подозрительных совпадений по IP.")
        else:
            lines.append(f"\n⚠️ Обнаружено игроков с твинками: **{flagged_count}** из **{len(online_players)}**.")

        embed = discord.Embed(
            title="🛡️ Экспресс-сканирование онлайна",
            description="\n".join(lines[:25]),
            color=Colors.GOLD if flagged_count > 0 else Colors.GREEN,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Vanilla Land • Security Scan")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @ui.button(label="История алертов", style=discord.ButtonStyle.secondary, emoji="📜", custom_id="btn_alts_audit_log", row=2)
    async def btn_audit_log(self, interaction: discord.Interaction, button: ui.Button):
        if not isinstance(interaction.user, discord.Member) or not self._check_perms(interaction.user):
            return await interaction.response.send_message("❌ Недостаточно прав.", ephemeral=True)

        incidents = self.db.get_security_incidents(10) if self.db else []
        if not incidents:
            return await interaction.response.send_message("ℹ️ Журнал инцидентов пуст — нарушений не зафиксировано.", ephemeral=True)

        lines = ["📜 **Последние 10 инцидентов безопасности:**\n"]
        for inc in incidents:
            t = inc.get("timestamp", "")
            p = inc.get("player", "N/A")
            ip = inc.get("ip", "N/A")
            typ = inc.get("type", "evasion")
            det = inc.get("details", "")
            lines.append(f"`{t}` • **`{p}`** (`{ip}`) — *{typ}*\n└ {det}")

        embed = discord.Embed(
            title="🛡️ Журнал инцидентов безопасности",
            description="\n".join(lines),
            color=Colors.DARK,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Vanilla Land • Security Audit Log")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Белый список", style=discord.ButtonStyle.secondary, emoji="🛡️", custom_id="btn_alts_whitelist", row=2)
    async def btn_whitelist(self, interaction: discord.Interaction, button: ui.Button):
        if not isinstance(interaction.user, discord.Member) or not self._check_perms(interaction.user):
            return await interaction.response.send_message("❌ Недостаточно прав.", ephemeral=True)

        wl = self.db.get_security_whitelist() if self.db else []
        if not wl:
            desc = "*Белый список пуст. Вы можете добавить игрока или IP через меню ниже.*"
        else:
            wl_lines = [f"• `{w['target']}` ({w['type']}) — *{w['reason'] or 'Без причины'}* (от {w['added_by']})" for w in wl[:15]]
            desc = "**Текущие исключения:**\n" + "\n".join(wl_lines)

        embed = discord.Embed(
            title="🛡️ Белый список безопасности (Исключения)",
            description=desc + "\n\n*Игроки и IP из белого списка игнорируются автокиком и автобаном при мультиаккаунтах.*",
            color=Colors.BLUE,
        )
        view = AltsWhitelistView(self.db, self.bot, self)
        await interaction.response.send_message(embed=view.get_embed(), view=view, ephemeral=True)

    @ui.button(label="Тест канала", style=discord.ButtonStyle.success, emoji="🔔", custom_id="btn_alts_test_alert", row=2)
    async def btn_test_alert(self, interaction: discord.Interaction, button: ui.Button):
        if not isinstance(interaction.user, discord.Member) or not self._check_perms(interaction.user):
            return await interaction.response.send_message("❌ Недостаточно прав.", ephemeral=True)

        sec_cog = self.bot.get_cog("SecurityCog")
        target_ch = await sec_cog._get_alert_channel() if sec_cog else None
        if not target_ch:
            return await interaction.response.send_message("❌ Не удалось найти канал для отправки алертов! Настройте канал кнопкой «Настроить канал».", ephemeral=True)

        try:
            now_msk = datetime.now(timezone(timedelta(hours=3))).strftime('%Y-%m-%d %H:%M:%S')
            desc_test = (
                f"**Статус:** Канал проверен и готов к приёму алертов!\n"
                f"**Канал доставки:** {target_ch.mention} (`{target_ch.id}`)\n"
                f"**Инициатор:** {interaction.user.mention}\n"
                f"**Время:** `{now_msk}`\n\n"
                f"*Уведомления об обходе банов в LiteBans и мультиаккаунтах будут приходить сюда.*"
            )
            test_embed = discord.Embed(
                title="🛡️ Тестовое оповещение системы безопасности",
                description=desc_test,
                color=Colors.GREEN,
                timestamp=datetime.now(timezone.utc),
            )
            test_embed.set_footer(text="Vanilla Land • LiteBans Guard Test")
            await target_ch.send(embed=test_embed)
            await interaction.response.send_message(f"✅ Тестовый алерт успешно доставлен в {target_ch.mention}!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка отправки в {target_ch.mention}: `{e}`", ephemeral=True)

    @ui.button(label="Обновить", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id="btn_alts_refresh", row=2)
    async def btn_refresh(self, interaction: discord.Interaction, button: ui.Button):
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.get_embed(), view=self)



class AltBanModal(ui.Modal, title="Блокировка за нарушение"):
    def __init__(self, login_player: str, default_reason: str, view: ui.View):
        super().__init__()
        self.login_player = str(login_player).strip().split()[0] if login_player else "Игрок"
        self.view = view
        self.reason_input = ui.TextInput(
            label="Причина бана",
            default=default_reason if default_reason else "Нарушение правил",
            placeholder="Причина, за которую был выдан бан...",
            required=True,
            max_length=200,
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        raw_reason = self.reason_input.value.strip()
        clean_reason = raw_reason.replace("\n", " ").replace("\r", " ").replace(";", " ").strip()
        if not clean_reason:
            clean_reason = "Нарушение правил"

        bridge_cog = get_bridge_cog(interaction.client)
        if bridge_cog and hasattr(bridge_cog, "broadcast_packet"):
            cmd = f"ban {self.login_player} {clean_reason}"
            await bridge_cog.broadcast_packet({"type": "execute_console_command", "command": cmd})
            msg = f"Игрок `{self.login_player}` успешно заблокирован с причиной: «{clean_reason}»."
        else:
            msg = "Мост с Minecraft сервером не подключен. Команда блокировки не отправлена."

        for item in self.view.children:
            if isinstance(item, ui.Button) and item.custom_id == "btn_ban_for_alt_evasion":
                item.disabled = True
                item.label = f"Забанен ({self.login_player})"
                item.style = discord.ButtonStyle.secondary

        try:
            if interaction.message:
                await interaction.message.edit(view=self.view)
        except Exception:
            pass

        embed = discord.Embed(
            title="Игрок заблокирован",
            description=(
                f"**Нарушитель:** `{self.login_player}`\n"
                f"**Причина:** `{clean_reason}`\n"
                f"**Модератор:** {interaction.user.mention}\n"
                f"**Время:** `{get_msk_now_str()}`"
            ),
            color=Colors.RED,
        )
        embed.set_footer(text="Vanilla Land • Модерация")
        await interaction.response.send_message(embed=embed)


class AltActionView(ui.View):
    """Панель действий под алертом обнаружения обхода бана"""
    def __init__(self, login_player: str, banned_nick: str, banned_reason: str, db: Optional[DatabaseManager], ip: str = ""):
        super().__init__(timeout=None)
        self.login_player = login_player
        self.banned_nick = banned_nick
        self.banned_reason = banned_reason
        self.db = db
        self.ip = ip

    def _check_perms(self, member: discord.Member) -> bool:
        if member.guild_permissions.administrator or member.guild_permissions.ban_members:
            return True
        return any(r.id in _admin_role_ids() for r in member.roles)

    def _state(self, interaction: discord.Interaction):
        """Состояние алерта: из БД по message_id (после рестарта) или из инстанса."""
        if self.db and interaction.message:
            data = self.db.get_security_alert(interaction.message.id)
            if data:
                return data["player"], data["banned_nick"], data["banned_reason"], data["ip"]
        return self.login_player, self.banned_nick, self.banned_reason, self.ip

    @ui.button(
        label="Забанить за обход",
        style=discord.ButtonStyle.danger,
        custom_id="btn_ban_for_alt_evasion",
        row=0,
    )
    async def ban_for_evasion(self, interaction: discord.Interaction, button: ui.Button):
        author = interaction.user
        if not isinstance(author, discord.Member):
            return await interaction.response.send_message("Ошибка доступа.", ephemeral=True)
        if not self._check_perms(author):
            return await interaction.response.send_message("Недостаточно прав для выполнения действия.", ephemeral=True)
        login_player, banned_nick, banned_reason, ip = self._state(interaction)
        if not login_player:
            return await interaction.response.send_message("Алерт устарел: нет данных игрока.", ephemeral=True)
        default_reason = f"Обход бана ({banned_nick}): {banned_reason}" if banned_nick != login_player else banned_reason
        view = AltActionView(login_player, banned_nick, banned_reason, self.db, ip)
        await interaction.response.send_modal(AltBanModal(login_player, default_reason, view))

    @ui.button(
        label="Исключить (Kick)",
        style=discord.ButtonStyle.secondary,
        custom_id="btn_kick_alt",
        row=0,
    )
    async def kick_alt(self, interaction: discord.Interaction, button: ui.Button):
        author = interaction.user
        if not isinstance(author, discord.Member) or not self._check_perms(author):
            return await interaction.response.send_message("Недостаточно прав.", ephemeral=True)
        login_player, banned_nick, banned_reason, ip = self._state(interaction)
        if not login_player:
            return await interaction.response.send_message("Алерт устарел: нет данных игрока.", ephemeral=True)

        bridge_cog = get_bridge_cog(interaction.client)
        clean_k_nick = login_player.strip().split()[0] if login_player else "Игрок"
        kick_reason = f"Обход бана ({banned_nick}): {banned_reason}"
        clean_k_reason = kick_reason.replace("\n", " ").replace("\n", " ").replace(";", " ").strip()
        if bridge_cog and hasattr(bridge_cog, "broadcast_packet"):
            await bridge_cog.broadcast_packet({"type": "execute_console_command", "command": f"kick {clean_k_nick} {clean_k_reason}"})
            new_view = AltActionView(login_player, banned_nick, banned_reason, self.db, ip)
            for child in new_view.children:
                if getattr(child, "custom_id", "") == "btn_kick_alt":
                    child.disabled = True
                    child.label = f"Исключен ({clean_k_nick})"
            try:
                if interaction.message:
                    await interaction.message.edit(view=new_view)
            except Exception:
                pass
            await interaction.response.send_message(f"Игрок `{clean_k_nick}` исключен с сервера.", ephemeral=True)
        else:
            await interaction.response.send_message("Мост с сервером недоступен.", ephemeral=True)

    @ui.button(
        label="Забанить по IP",
        style=discord.ButtonStyle.danger,
        custom_id="btn_ipban_alt",
        row=0,
    )
    async def ipban_alt(self, interaction: discord.Interaction, button: ui.Button):
        author = interaction.user
        if not isinstance(author, discord.Member) or not self._check_perms(author):
            return await interaction.response.send_message("Недостаточно прав.", ephemeral=True)
        login_player, banned_nick, banned_reason, ip = self._state(interaction)
        if not login_player:
            return await interaction.response.send_message("Алерт устарел: нет данных игрока.", ephemeral=True)

        bridge_cog = get_bridge_cog(interaction.client)
        clean_k_nick = login_player.strip().split()[0] if login_player else "Игрок"
        ipban_reason = f"Обход бана ({banned_nick}): {banned_reason}"
        clean_k_reason = ipban_reason.replace("\n", " ").replace("\n", " ").replace(";", " ").strip()
        if bridge_cog and hasattr(bridge_cog, "broadcast_packet"):
            await bridge_cog.broadcast_packet({"type": "execute_console_command", "command": f"ban-ip {clean_k_nick} {clean_k_reason}"})
            new_view = AltActionView(login_player, banned_nick, banned_reason, self.db, ip)
            for child in new_view.children:
                if getattr(child, "custom_id", "") == "btn_ipban_alt":
                    child.disabled = True
                    child.label = f"IP забанен ({clean_k_nick})"
            try:
                if interaction.message:
                    await interaction.message.edit(view=new_view)
            except Exception:
                pass
            await interaction.response.send_message(f"IP адрес игрока `{clean_k_nick}` заблокирован на сервере.", ephemeral=True)
        else:
            await interaction.response.send_message("Мост с сервером недоступен.", ephemeral=True)


def _db_quick_check(db) -> None:
    with db._get_connection() as conn:
        conn.execute("PRAGMA quick_check").fetchone()


def make_gauge_bar(val: float, max_val: float, length: int = 8) -> str:
    """Генерирует аккуратную шкалу прогресса без тяжелых картинок"""
    if max_val <= 0:
        return "░" * length
    pct = max(0.0, min(1.0, val / max_val))
    filled = int(round(pct * length))
    return "█" * filled + "░" * (length - filled)


class HealthcheckAdminView(ui.View):
    """Интерактивная панель мониторинга и глубокой диагностики систем бота и сервера (Tech Admin HUD)"""
    def __init__(self, security_cog: "SecurityCog", author_id: int):
        super().__init__(timeout=180)
        self.security_cog = security_cog
        self.author_id = author_id
        self.message: Optional[discord.Message] = None

    async def on_timeout(self):
        """Отключает интерактивные кнопки по истечении тайм-аута сессии"""
        for item in self.children:
            if isinstance(item, ui.Button) and item.style != discord.ButtonStyle.link:
                item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        guild = interaction.guild or (interaction.client.get_guild(Config.GUILD_ID) if Config.GUILD_ID else None)
        member = interaction.user
        if guild and not isinstance(member, discord.Member):
            m = guild.get_member(member.id)
            if m:
                member = m

        is_owner = (interaction.client.owner_id and member.id == interaction.client.owner_id) or \
                   (interaction.client.owner_ids and member.id in interaction.client.owner_ids)
        if is_owner or (guild and member.id == guild.owner_id):
            return True

        if isinstance(member, discord.Member):
            if member.guild_permissions.administrator:
                return True
            if any(r.id in _admin_role_ids() for r in member.roles):
                return True

        await interaction.response.send_message(
            "⛔ Эта интерактивная диагностическая панель доступна только технической администрации.",
            ephemeral=True
        )
        return False

    async def build_embed(self) -> discord.Embed:
        bot = self.security_cog.bot
        db = self.security_cog.db
        guild = bot.get_guild(Config.GUILD_ID) or (bot.guilds[0] if bot.guilds else None)
        now_ts = int(time.time())

        # 1. Discord Latency
        try:
            discord_ping = round(bot.latency * 1000) if (hasattr(bot, "latency") and bot.latency is not None and not math.isnan(bot.latency)) else 0
        except Exception:
            discord_ping = 0

        # 2. Мост Minecraft и статус сервера
        bridge_cog = get_bridge_cog(bot)
        bridge_connected = False
        maint_enabled = False
        maint_reason = "Технические работы"
        mc_start_ts = 0

        if bridge_cog:
            active_socks = getattr(bridge_cog, "active_sockets", set())
            bridge_connected = len(active_socks) > 0
            maint_enabled = bool(getattr(bridge_cog, "maintenance_enabled", False))
            maint_reason = str(getattr(bridge_cog, "maintenance_reason", "Технические работы"))
            mc_start_ts = int(getattr(bridge_cog, "mc_server_start_time", 0))

        # 3. Аптаймы
        bot_start_ts = int(getattr(bot, "start_time", time.time()))
        if mc_start_ts > 0 and bridge_connected:
            mc_uptime_str = f"<t:{mc_start_ts}:R>"
        else:
            mc_uptime_str = "`В сети`" if bridge_connected else "`Оффлайн`"

        # 4. База данных SQLite (I/O замер) и размер файла
        db_speed = 0.0
        db_status = "🔴 Ошибка"
        db_stats = {}
        db_size_str = "N/A"
        if db:
            try:
                t0 = time.perf_counter()
                await asyncio.to_thread(_db_quick_check, db)
                db_speed = round((time.perf_counter() - t0) * 1000, 2)
                db_status = f"🟢 `{db_speed} ms` (PRAGMA OK)"
                if hasattr(db, "get_db_stats"):
                    db_stats = db.get_db_stats()
                if os.path.exists(Config.DB_PATH):
                    db_size_kb = round(os.path.getsize(Config.DB_PATH) / 1024, 1)
                    db_size_str = f"{db_size_kb} KB"
            except Exception as e:
                db_status = f"🔴 Сбой: {e}"

        # 5. Реальное дисковое пространство хостинга (SSD)
        try:
            d_total, d_used, d_free = await asyncio.to_thread(shutil.disk_usage, ".")
            used_gb = round(d_used / (1024 ** 3), 1)
            total_gb = round(d_total / (1024 ** 3), 1)
            disk_pct = round((d_used / d_total) * 100, 1)
            disk_bar = make_gauge_bar(d_used, d_total, 8)
            disk_str = f"`[{disk_bar}]` {used_gb} / {total_gb} GB *({disk_pct}%)*"
        except Exception:
            disk_str = "Штатный"

        # 6. Живые сетевые замеры: TCP порт и Web-сервисы (asyncio.gather)
        ip_display = Config.SERVER_IP or "vanillaland.ru-mc.ru"
        try:
            tcp_task = ping_tcp_port(ip_display, 25565, timeout_sec=2.0)
            site_task = ping_http_url(Config.SITE_URL, timeout_sec=2.0)
            store_task = ping_http_url(Config.DONATE_URL, timeout_sec=2.0)
            tcp_res, site_res, store_res = await asyncio.gather(tcp_task, site_task, store_task)
        except Exception:
            tcp_res = "🟢 Открыт"
            site_res = "*Не настроен*"
            store_res = "*Не настроен*"

        # 7. Права бота и безопасность
        perms = getattr(guild.me, "guild_permissions", None) if (guild and getattr(guild, "me", None)) else None
        critical_perms = {
            "Роли": perms.manage_roles if perms else False,
            "Каналы": perms.manage_channels if perms else False,
            "Вебхуки": perms.manage_webhooks if perms else False,
            "Аудит": perms.view_audit_log if perms else False,
        }
        missing_perms = [name for name, has in critical_perms.items() if not has]
        perms_status = "🟢 Все 4 разрешения активны" if not missing_perms else f"🔴 Не хватает: {', '.join(missing_perms)}"

        lockdown_on = (db.get_setting("verification_lockdown_enabled") == "true") if db else False
        lockdown_str = "🔴 Включен" if lockdown_on else "🟢 Выключен"

        # 8. Память бота и задачи
        ram_mb = "N/A"
        try:
            import psutil
            process = psutil.Process(os.getpid())
            ram_mb = f"{round(process.memory_info().rss / (1024 * 1024), 1)} MB"
        except Exception:
            try:
                with open("/proc/self/statm", "r") as f:
                    pages = int(f.read().split()[1])
                    ram_mb = f"{round(pages * 4096 / (1024 * 1024), 1)} MB"
            except Exception:
                ram_mb = "Штатный"

        tasks_cnt = len(asyncio.all_tasks())

        # Определение статуса сервера
        if maint_enabled:
            status_title = "🟡 ТЕХНИЧЕСКИЕ РАБОТЫ"
            status_desc = f"На сервере ведутся регламентные работы: *{maint_reason}*"
            color = Colors.YELLOW
        elif bridge_connected:
            status_title = "🟢 СЕРВЕР В СЕТИ"
            status_desc = "Синхронизация с ядром Paper 26.3 активна"
            color = Colors.GREEN
        else:
            status_title = "🔴 СЕРВЕР ОФФЛАЙН"
            status_desc = "Соединение с мостом WebSocket разорвано или сервер выключен"
            color = Colors.RED

        embed = discord.Embed(
            title="🎮 Vanilla Land • Системный мониторинг & Диагностика",
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        embed.description = (
            f"### {status_title}\n"
            f"> **Адрес сервера:** `{ip_display}:25565` • **Версия:** `26.3 Java`\n"
            f"> **Аптайм Minecraft:** {mc_uptime_str} • **Аптайм бота:** <t:{bot_start_ts}:R>\n"
            f"> **Срез данных:** <t:{now_ts}:T> (<t:{now_ts}:R>)"
        )

        # Модуль 1: Сеть и веб-сервисы (inline=True)
        bridge_status_str = "🟢 Активен (25549)" if bridge_connected else "🔴 Разорван"
        embed.add_field(
            name="🌐 Сеть & Веб-сервисы",
            value=(
                f"• **Игровой порт:** {tcp_res}\n"
                f"• **WebSocket мост:** {bridge_status_str}\n"
                f"• **Discord Gateway:** `{discord_ping} ms`\n"
                f"• **Сайт проекта:** {site_res}\n"
                f"• **Магазин:** {store_res}"
            ),
            inline=True,
        )

        # Модуль 2: Хостинг и база данных (inline=True)
        embed.add_field(
            name="💾 Хостинг & База данных",
            value=(
                f"• **Диск SSD:** {disk_str}\n"
                f"• **База SQLite:** {db_status}\n"
                f"• **Бэкап мира:** 🟢 DriveBackupV2 (каждые 6ч)\n"
                f"• **RAM процесса:** `{ram_mb}` ({tasks_cnt} задач)\n"
                f"• **Размер БД:** `{db_size_str}`"
            ),
            inline=True,
        )

        # Модуль 3: Безопасность и доступ (inline=False)
        tickets_cnt = db_stats.get("active_tickets", 0)
        linked_cnt = db_stats.get("linked_accounts", 0)
        sessions_cnt = db_stats.get("active_sessions", 0)
        embed.add_field(
            name="🛡️ Безопасность и Доступ",
            value=(
                f"• **2FA IP-сессии:** **{sessions_cnt}** активная • Привязано аккаунтов: **{linked_cnt}**\n"
                f"• **Рейд-фильтр:** {lockdown_str}\n"
                f"• **Discord права:** {perms_status}"
            ),
            inline=False,
        )

        embed.set_footer(text=f"Vanilla Land Diagnostics • Порт моста: {Config.BRIDGE_PORT}")
        return embed

    @ui.button(label="Обновить", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id="hc:refresh", row=0)
    async def refresh_btn(self, interaction: discord.Interaction, button: ui.Button):
        embed = await self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)



    @ui.button(label="Тест сети", style=discord.ButtonStyle.secondary, emoji="⚡", custom_id="hc:net", row=0)
    async def net_test_btn(self, interaction: discord.Interaction, button: ui.Button):
        bot = self.security_cog.bot
        try:
            gw_ping = round(bot.latency * 1000) if (hasattr(bot, "latency") and bot.latency is not None and not math.isnan(bot.latency)) else 0
        except Exception:
            gw_ping = 0

        db_speed_str = "N/A"
        if self.security_cog.db:
            try:
                t0 = time.perf_counter()
                with self.security_cog.db._get_connection() as conn:
                    conn.execute("SELECT 1").fetchone()
                db_speed = round((time.perf_counter() - t0) * 1000, 2)
                db_speed_str = f"{db_speed} ms"
            except Exception as e:
                db_speed_str = f"Ошибка ({type(e).__name__})"

        bridge_cog = get_bridge_cog(bot)
        sockets_cnt = len(getattr(bridge_cog, "active_sockets", set())) if bridge_cog else 0

        embed = discord.Embed(
            title="⚡ Диагностика сетевых задержек • Vanilla Land",
            description=(
                f"```fix\n"
                f"Discord Gateway:     {gw_ping} ms\n"
                f"SQLite Roundtrip:    {db_speed_str}\n"
                f"Active Sockets:      {sockets_cnt} соединений\n"
                f"Cloudflare Nginx:    bridge.vanillaland.fun:80\n"
                f"Target Port:         172.18.0.1:{Config.BRIDGE_PORT}\n"
                f"```"
            ),
            color=Colors.GREEN if gw_ping < 120 else Colors.YELLOW,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Очистить кэш (GC)", style=discord.ButtonStyle.secondary, emoji="🧹", custom_id="hc:gc", row=0)
    async def gc_btn(self, interaction: discord.Interaction, button: ui.Button):
        t0 = time.perf_counter()
        collected = gc.collect()
        cleaned_codes = 0
        if self.security_cog.db:
            try:
                cleaned_codes = self.security_cog.db.cleanup_expired_codes()
            except Exception:
                pass
        deleted_junk = 0
        try:
            for jf in os.listdir("."):
                if "\\" in jf and os.path.isfile(jf):
                    try:
                        os.remove(jf)
                        deleted_junk += 1
                    except Exception:
                        pass
        except Exception:
            pass

        dur_ms = round((time.perf_counter() - t0) * 1000, 1)

        ram_mb = "N/A"
        try:
            import psutil
            ram_mb = f"{round(psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024), 1)} МБ"
        except Exception:
            pass

        junk_line = f"Удалено файлов с обратными \\:  {deleted_junk}\n" if deleted_junk > 0 else ""

        embed = discord.Embed(
            title="🧹 Очистка системного кэша и GC",
            description=(
                f"```fix\n"
                f"Освобождено объектов GC:     {collected}\n"
                f"Удалено просроченных 2FA:    {cleaned_codes}\n"
                f"{junk_line}"
                f"Время очистки:               {dur_ms} мс\n"
                f"Текущая RAM процесса:        {ram_mb}\n"
                f"```"
            ),
            color=Colors.GREEN,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ui.button(label="Экспорт дампа", style=discord.ButtonStyle.secondary, emoji="📄", custom_id="hc:dump", row=0)
    async def dump_btn(self, interaction: discord.Interaction, button: ui.Button):
        bot = self.security_cog.bot
        bridge_cog = get_bridge_cog(bot)

        dump = {
            "timestamp": int(time.time()),
            "msk_time": get_msk_now_str(),
            "bot": {
                "user": str(bot.user),
                "user_id": bot.user.id if bot.user else None,
                "latency_ms": round(bot.latency * 1000, 2) if (hasattr(bot, "latency") and bot.latency is not None and not math.isnan(bot.latency)) else 0.0,
                "uptime_seconds": round(time.time() - getattr(bot, "start_time", time.time())),
                "guilds_count": len(bot.guilds),
            },
            "bridge": {
                "connected": len(getattr(bridge_cog, "active_sockets", set())) > 0 if bridge_cog else False,
                "online": getattr(bridge_cog, "mc_online", 0) if bridge_cog else 0,
                "max": getattr(bridge_cog, "mc_max", 0) if bridge_cog else 0,
                "tps": getattr(bridge_cog, "mc_tps", 0.0) if bridge_cog else 0.0,
                "mspt": getattr(bridge_cog, "mc_mspt", 0.0) if bridge_cog else 0.0,
                "mem_used_mb": getattr(bridge_cog, "mc_mem_used", 0) if bridge_cog else 0,
                "mem_max_mb": getattr(bridge_cog, "mc_mem_max", 0) if bridge_cog else 0,
                "players": getattr(bridge_cog, "mc_players", []) if bridge_cog else [],
            },
            "database": self.security_cog.db.get_db_stats() if hasattr(self.security_cog.db, "get_db_stats") else {},
        }
        json_str = json.dumps(dump, ensure_ascii=False, indent=2)
        if len(json_str) < 1900:
            await interaction.response.send_message(f"```json\n{json_str}\n```", ephemeral=True)
        else:
            import io
            f = discord.File(io.BytesIO(json_str.encode("utf-8")), filename="healthcheck_dump.json")
            await interaction.response.send_message("📄 Системный дамп состояния в файле:", file=f, ephemeral=True)


class SecurityCog(commands.Cog, name="Безопасность"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db: Optional[DatabaseManager] = getattr(bot, "db", None)
        self.active_player_ips: dict[str, str] = {}

        # Автоматическая очистка ошибочно распакованных файлов с обратными слэшами
        try:
            junk = [f for f in os.listdir(".") if "\\" in f and os.path.isfile(f)]
            for jf in junk:
                try:
                    os.remove(jf)
                except Exception:
                    pass
            if junk:
                logger.info(f"Автоматически удалено {len(junk)} мусорных файлов с обратными слэшами из корня.")
        except Exception:
            pass

    # --- СЛУШАТЕЛЬ ПАКЕТОВ МОСТА ---
        # --- СЛУШАТЕЛЬ ПАКЕТОВ МОСТА ---
    @commands.Cog.listener()
    async def on_bridge_packet(self, p_type: str, data: dict):
        if p_type == "join":
            await self.handle_player_join_security(data)
        elif p_type == "quit":
            player = str(data.get("player", "")).strip()
            if player:
                self.active_player_ips.pop(player.lower(), None)
        elif p_type in ("bridge_reconnect", "lifecycle"):
            if data.get("event") == "stop" or p_type == "bridge_reconnect":
                self.active_player_ips.clear()
        elif p_type == "stats":
            # Синхронизация реального онлайна и отсеивание фантомных сессий игроков
            online_names = {str(p).lower() for p in data.get("players", [])}
            if online_names:
                phantoms = [p for p in list(self.active_player_ips.keys()) if p not in online_names]
                for ph in phantoms:
                    self.active_player_ips.pop(ph, None)
        elif p_type == "alts_bans_result":
            logger.info("Получен пакет alts_bans_result для игрока %s (забанено: %d, чисто: %d)",
                        data.get("player"), len(data.get("banned", [])), len(data.get("clean", [])))
            await self.handle_alts_bans_result(data)
        elif p_type == "admin_perm_alert":
            await self.handle_admin_perm_alert(data)

    def _can_send_to(self, ch: Any) -> bool:
        """Проверяет, что бот может отправлять сообщения и эмбеды в данный канал"""
        if not ch or not hasattr(ch, "send"):
            return False
        guild = getattr(ch, "guild", None)
        if guild and guild.me and hasattr(ch, "permissions_for"):
            perms = ch.permissions_for(guild.me)
            return bool(perms.view_channel and perms.send_messages and perms.embed_links)
        return True

    async def _resolve_channel(self, cid: int) -> Optional[Any]:
        """Безопасно резолвит канал по ID через кэш и Discord API с проверкой прав"""
        if not cid or cid <= 0:
            return None
        ch = self.bot.get_channel(cid)
        if ch and self._can_send_to(ch):
            return ch
        try:
            ch = await self.bot.fetch_channel(cid)
            if ch and self._can_send_to(ch):
                return ch
        except Exception:
            pass
        return None

    async def _get_alert_channel(self) -> Optional[Any]:
        """
        Находит наилучший доступный канал для оповещений безопасности:
        1. Настроенный вручную через панель / базу (alts_alert_channel_id)
        2. Config.ALTS_ALERT_CHANNEL_ID (из .env)
        3. Config.EVENTS_CHANNEL_ID (канал событий сервера)
        4. Config.ADMIN_LOG_CHANNEL_ID / LOG_CHANNEL_ID (логи)
        5. Поиск по имени: #обход-банов, #alts, #алерты, #модерация, #security, #логи
        6. Первый текстовый канал гильдии, где бот имеет права отправки
        """
        # 1. Из базы данных
        if self.db:
            saved = self.db.get_setting("alts_alert_channel_id")
            if saved and saved.isdigit():
                ch = await self._resolve_channel(int(saved))
                if ch:
                    return ch

        # 2. Config.ALTS_ALERT_CHANNEL_ID
        env_alt = getattr(Config, "ALTS_ALERT_CHANNEL_ID", 0)
        if env_alt and env_alt > 0:
            ch = await self._resolve_channel(env_alt)
            if ch:
                return ch

        # 3. Перебираем кандидаты из конфигурации по очереди (НЕ прерывая цикл при первой ошибке!)
        for attr in ("EVENTS_CHANNEL_ID", "ADMIN_LOG_CHANNEL_ID", "LOG_CHANNEL_ID"):
            cid = getattr(Config, attr, None)
            if cid and cid > 0:
                ch = await self._resolve_channel(cid)
                if ch:
                    return ch

        # 4. Поиск в гильдиях по ключевым именам каналов
        guild = None
        if Config.GUILD_ID:
            guild = self.bot.get_guild(Config.GUILD_ID)
        if not guild and self.bot.guilds:
            guild = self.bot.guilds[0]

        if guild:
            name_keywords = ("обход", "alt", "алерт", "alert", "безопасност", "security", "модер", "лог")
            for c in guild.text_channels:
                c_name = c.name.lower()
                if any(kw in c_name for kw in name_keywords) and self._can_send_to(c):
                    return c

            # 5. Первый канал, где есть права на отправку
            for c in guild.text_channels:
                if self._can_send_to(c):
                    return c

        return None

    async def handle_player_join_security(self, data: dict):
        """Проверка мультиаккаунтов, лимита одновременных подключений и статуса банов в LiteBans"""
        player = str(data.get("player", "")).strip()
        raw_ip = str(data.get("ip", "127.0.0.1")).strip()
        if not player or not self.db:
            return

        clean_ip = self.db._normalize_ip(raw_ip) if hasattr(self.db, "_normalize_ip") else raw_ip.lstrip("/").split(":")[0].strip()
        is_local = clean_ip.lower() in ("127.0.0.1", "0.0.0.0", "localhost", "::1", "unknown", "none", "n/a", "")

        if not is_local:
            self.db.record_player_ip(player, clean_ip)

            # Проверка белого списка исключений безопасности
            is_whitelisted = self.db.is_security_whitelisted(player, clean_ip) if hasattr(self.db, "is_security_whitelisted") else False

            # 1. Проверка лимита одновременных подключений с одного IP (анти-мультибокс)
            raw_limit = self.db.get_setting("alts_max_per_ip", "2")
            try:
                max_per_ip = max(1, int(raw_limit))
            except (ValueError, TypeError):
                max_per_ip = 2

            same_ip_online = [
                p_name for p_name, pip in self.active_player_ips.items()
                if pip == clean_ip and p_name != player.lower()
            ]

            if not is_whitelisted and len(same_ip_online) >= max_per_ip:
                logger.warning(
                    "Превышен лимит подключений с IP %s для %s (онлайн сейчас: %s, лимит: %d)",
                    clean_ip, player, same_ip_online, max_per_ip
                )
                bridge_cog = get_bridge_cog(self.bot)
                if bridge_cog and hasattr(bridge_cog, "broadcast_packet"):
                    kick_cmd = f"kick {player} Превышен лимит аккаунтов с одного IP (максимум {max_per_ip})"
                    await bridge_cog.broadcast_packet({
                        "type": "execute_console_command",
                        "command": kick_cmd,
                    })

                target_channel = await self._get_alert_channel()
                if target_channel:
                    online_list = ", ".join(f"`{p}`" for p in same_ip_online)
                    desc_mb = (
                        f"**Игрок:** `{player}` (кикнут с сервера)\n"
                        f"**IP адрес:** `{clean_ip}`\n"
                        f"**Лимит на IP:** `{max_per_ip}` акк. одновременно\n"
                        f"**Уже на сервере ({len(same_ip_online)}):** {online_list}\n\n"
                        f"*Игрок был автоматически исключен для предотвращения мультибокса.*"
                    )
                    embed = discord.Embed(
                        title="⚠️ Превышен лимит подключений с одного IP",
                        description=desc_mb,
                        color=Colors.RED,
                        timestamp=datetime.now(timezone.utc),
                    )
                    embed.set_thumbnail(url=f"https://mc-heads.net/avatar/{player}/128.png")
                    embed.set_footer(text="Vanilla Land • Анти-мультибокс")
                    try:
                        await target_channel.send(embed=embed)
                    except Exception as e:
                        logger.error(f"Ошибка отправки алерта мультибокса: {e}")

                if hasattr(self.db, "record_security_incident"):
                    self.db.record_security_incident(
                        player=player,
                        ip=clean_ip,
                        incident_type="multibox_limit",
                        details=f"Превышен лимит {max_per_ip} на IP. На сервере: {', '.join(same_ip_online)}"
                    )
                return

            self.active_player_ips[player.lower()] = clean_ip

        # 2. Проверка истории по 100% точному IP (без ложных срабатываний по подсетям)
        alts_data = self.db.get_player_alts(player, current_ip=clean_ip)
        exact_alts_list = alts_data.get("alts", [])

        # Формируем список кандидатов для LiteBans (сам игрок + все точные твинки по IP)
        candidate_names = set([player])
        for a in exact_alts_list:
            name = a.get("player_name", "").strip()
            if name:
                candidate_names.add(name)

        bridge_cog = get_bridge_cog(self.bot)
        if bridge_cog and hasattr(bridge_cog, "broadcast_packet"):
            alts_str = ",".join(candidate_names)
            logger.info("Запрос проверки LiteBans по точному IP для %s (аккаунты: %s, IP: %s)", player, alts_str, clean_ip)
            if hasattr(bridge_cog, "register_alt_check"):
                bridge_cog.register_alt_check(player, ttl=30.0, manual=False)
            await bridge_cog.broadcast_packet({
                "type": "check_alts_bans",
                "player": player,
                "ip": clean_ip,
                "alts": alts_str,
            })

    async def handle_alts_bans_result(self, data: dict):
        """Обрабатывает результат комплексной проверки твинков и банов LiteBans из Minecraft"""
        login_player = data.get("player", "Игрок")
        ip = data.get("ip", "127.0.0.1")
        banned = data.get("banned", [])
        clean = data.get("clean", [])

        # Anti-spoof: обрабатываем только ответы на собственные автоматические запросы.
        # Ручные проверки (!whois / !alts) и посторонние пакеты не должны вызывать автобаны.
        bridge_cog = get_bridge_cog(self.bot)
        if bridge_cog is not None and hasattr(bridge_cog, "consume_alt_check"):
            if not bridge_cog.consume_alt_check(login_player):
                logger.warning(
                    "Отброшен незапрошенный/ручной alts_bans_result для %s (anti-spoof)", login_player
                )
                return

        if not banned and not clean:
            return

        target_channel = await self._get_alert_channel()
        if not target_channel:
            logger.critical("КРИТИЧЕСКАЯ ОШИБКА: Ни один канал для отправки алертов безопасности не доступен боту!")
            return

        mode = self.db.get_setting("alts_protection_mode", "alert").lower() if self.db else "alert"
        vpn_check = (self.db.get_setting("alts_vpn_check", "true").lower() == "true") if self.db else True

        # Проверка белого списка исключений безопасности
        is_whitelisted = self.db.is_security_whitelisted(login_player, ip) if hasattr(self.db, "is_security_whitelisted") else False
        if is_whitelisted:
            logger.info("Игрок %s (IP: %s) находится в белом списке исключений. Авто-санкции опущены.", login_player, ip)
            mode = "alert"

        # Сведения о провайдере / VPN
        intel = await check_ip_intel(ip) if vpn_check else None
        net_lines = []
        if intel:
            isp = intel.get("isp", "Не определён")
            country = intel.get("country", "")
            city = intel.get("city", "")
            loc = f"{country}, {city}".strip(", ") if (country or city) else "Не определена"
            if intel.get("is_vpn"):
                net_type = "VPN обнаружен"
            else:
                isp_clean = isp if isp and isp != "Не определён" else "Обычный провайдер"
                net_type = f"Провайдер — {isp_clean}"
            net_lines.append(f"• **Локация:** {loc}")
            net_lines.append(f"• **Тип сети:** `{net_type}`")
        net_block = "\n".join(net_lines)

        bridge_cog = get_bridge_cog(self.bot)
        online_set = {p.lower() for p in getattr(bridge_cog, "mc_players", [])} if bridge_cog else set()

        other_banned = [b for b in banned if b.get("player", "").lower() != login_player.lower()]
        is_login_banned = any(b.get("player", "").lower() == login_player.lower() for b in banned)

        # СЦЕНАРИЙ 1: ОБХОД БАНА (с этого IP заходил аккаунт, у которого в LiteBans активен бан)
        if other_banned:
            primary_banned = other_banned[0]
            b_nick = primary_banned.get("player", "Игрок")
            b_reason = primary_banned.get("reason", "Нарушение правил")
            b_by = primary_banned.get("banned_by", "Console")
            b_dur = primary_banned.get("duration", "Навсегда")

            clean_k_reason = f"Обход бана ({b_nick}): {b_reason}".replace("\n", " ").replace("\r", " ").replace(";", " ").strip()
            clean_k_nick = login_player.strip().split()[0] if login_player else "Игрок"

            if hasattr(self.db, "record_security_incident"):
                self.db.record_security_incident(
                    player=login_player,
                    ip=ip,
                    incident_type="ban_evasion",
                    details=f"Забаненный твинк: {b_nick} | Причина: {b_reason} | Выдал: {b_by}"
                )

            if mode == "autoban":
                if bridge_cog and hasattr(bridge_cog, "broadcast_packet"):
                    ban_cmd = f"ban {clean_k_nick} {clean_k_reason}"
                    await bridge_cog.broadcast_packet({
                        "type": "execute_console_command",
                        "command": ban_cmd,
                    })
                action_status = "Забанен на сервере (Auto-ban)"
            elif mode == "autokick":
                if bridge_cog and hasattr(bridge_cog, "broadcast_packet"):
                    kick_cmd = f"kick {clean_k_nick} {clean_k_reason}"
                    await bridge_cog.broadcast_packet({
                        "type": "execute_console_command",
                        "command": kick_cmd,
                    })
                action_status = "Исключен с сервера (Auto-kick)"
            else:
                action_status = "Оповещение (решение за персоналом)"

            accounts_block = []
            for b in other_banned:
                p_nick = b.get("player", "Игрок")
                p_reason = b.get("reason", "Нарушение правил")
                p_dur = b.get("duration", "Навсегда")
                p_by = b.get("banned_by", "Console")
                accounts_block.append(f"• `{p_nick}` • `[Забанен]` «{p_reason}» ({p_dur}, выдал `{p_by}`)")

            # Текущий игрок
            login_on_tag = "`[Онлайн]`" if (login_player.lower() in online_set) else "`[Только зашел]`"
            accounts_block.append(f"• `{login_player}` • {login_on_tag} *(текущий)*")

            # Чистые твинки по этому же IP
            other_banned_lowers = {b.get("player", "").lower() for b in other_banned}
            clean_alts = []
            for c in clean:
                c_nick = c.get("player", "") if isinstance(c, dict) else str(c)
                if c_nick and c_nick.lower() != login_player.lower() and c_nick.lower() not in other_banned_lowers:
                    c_online = c.get("online") if isinstance(c, dict) else (c_nick.lower() in online_set)
                    clean_alts.append((c_nick, c_online))

            for c_nick, c_online in clean_alts:
                c_tag = "`[Онлайн]`" if c_online else "`[Оффлайн]`"
                accounts_block.append(f"• `{c_nick}` • {c_tag}")

            accounts_text = "\n".join(accounts_block)

            desc_parts = [
                f"**Входящий игрок:** `{login_player}`",
                f"**IP адрес:** `{ip}`",
                f"**Основная причина бана:** «{b_reason}» *(аккаунт: `{b_nick}`, выдал `{b_by}`)*",
                f"**Действие системы:** `{action_status}`",
            ]
            if net_block:
                desc_parts.append(net_block)
            desc_parts.extend([
                f"\n**Связанные аккаунты по точному IP ({len(accounts_block)}):**",
                f"{accounts_text}",
                "\n*Все аккаунты имеют идентичный IP адрес. Данные о бане получены напрямую из LiteBans.*"
            ])

            embed = discord.Embed(
                title="🚨 Обнаружен возможный обход бана!",
                description="\n".join(desc_parts),
                color=Colors.RED,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url=f"https://mc-heads.net/avatar/{login_player}/128.png")
            embed.set_footer(text=f"Vanilla Land • LiteBans • Режим: {mode.upper()}")

            view = AltActionView(login_player, b_nick, b_reason, self.db, ip=ip)
            try:
                alert_msg = await target_channel.send(embed=embed, view=view)
                if self.db:
                    self.db.save_security_alert(alert_msg.id, login_player, b_nick, b_reason, ip)
            except discord.Forbidden:
                logger.error("Нет прав на отправку алертов в канал %s. Пытаюсь отправить в резервный...", target_channel)
                guild = getattr(target_channel, "guild", None) or (self.bot.guilds[0] if self.bot.guilds else None)
                if guild:
                    for fallback_ch in guild.text_channels:
                        if fallback_ch.id != getattr(target_channel, "id", 0) and self._can_send_to(fallback_ch):
                            try:
                                fb_msg = await fallback_ch.send(
                                    content="⚠️ **Внимание персонала:** Основной канал алертов недоступен. Алерт перенаправлен сюда:",
                                    embed=embed,
                                    view=view
                                )
                                if self.db:
                                    self.db.save_security_alert(fb_msg.id, login_player, b_nick, b_reason, ip)
                                break
                            except Exception:
                                continue
            except Exception as e:
                logger.error(f"Ошибка при отправке алерта об обходе банов: {e}", exc_info=True)

            logger.warning("АЛЕРТ ОБХОДА: %s зашел с IP %s (твинк: %s забанен за '%s', режим: %s)", login_player, ip, b_nick, b_reason, mode)

        # СЦЕНАРИЙ 2: САМ ВХОДЯЩИЙ ИГРОК ЗАБАНЕН В LiteBans
        elif is_login_banned:
            b_item = next(b for b in banned if b.get("player", "").lower() == login_player.lower())
            b_reason = b_item.get("reason", "Нарушение правил")
            b_dur = b_item.get("duration", "Навсегда")
            b_by = b_item.get("banned_by", "Console")

            clean_k_reason = b_reason.replace("\n", " ").replace("\r", " ").replace(";", " ").strip() if b_reason else "Нарушение правил"
            clean_k_nick = login_player.strip().split()[0] if login_player else "Игрок"

            if hasattr(self.db, "record_security_incident"):
                self.db.record_security_incident(
                    player=login_player,
                    ip=ip,
                    incident_type="banned_login",
                    details=f"Забаненный игрок вошел: {b_reason} (выдал: {b_by})"
                )

            if mode in ("autoban", "autokick"):
                if bridge_cog and hasattr(bridge_cog, "broadcast_packet"):
                    kick_cmd = f"kick {clean_k_nick} {clean_k_reason}"
                    await bridge_cog.broadcast_packet({
                        "type": "execute_console_command",
                        "command": kick_cmd,
                    })

            desc_parts = [
                f"**Игрок:** `{login_player}` • `[Забанен]`",
                f"**IP адрес:** `{ip}`",
                "**Статус в LiteBans:** Активный бан",
                f"**Причина бана:** «{b_reason}»",
                f"**Срок:** {b_dur} *(выдал `{b_by}`)*",
            ]
            if net_block:
                desc_parts.append(net_block)

            embed = discord.Embed(
                title="⛔ Вход забаненного игрока",
                description="\n".join(desc_parts),
                color=Colors.RED,
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_thumbnail(url=f"https://mc-heads.net/avatar/{login_player}/128.png")
            embed.set_footer(text="Vanilla Land • LiteBans")
            view = AltActionView(login_player, login_player, b_reason, self.db, ip=ip)
            try:
                alert_msg = await target_channel.send(embed=embed, view=view)
                if self.db:
                    self.db.save_security_alert(alert_msg.id, login_player, login_player, b_reason, ip)
            except Exception as e:
                logger.error(f"Ошибка отправки алерта забаненного входа: {e}")

        # СЦЕНАРИЙ 3: ЧИСТЫЕ ТВИНКИ
        else:
            only_bans = (self.db.get_setting("alts_alert_only_bans", "true").lower() == "true") if self.db else True
            if only_bans:
                return

            clean_names = []
            for c in clean:
                c_nick = c.get("player", "") if isinstance(c, dict) else str(c)
                if c_nick and c_nick.lower() != login_player.lower():
                    c_online = c.get("online") if isinstance(c, dict) else (c_nick.lower() in online_set)
                    clean_names.append((c_nick, c_online))

            if clean_names:
                accounts_block = [f"• `{login_player}` • `[Онлайн]` *(текущий)*"]
                for c_nick, c_online in clean_names:
                    c_tag = "`[Онлайн]`" if c_online else "`[Оффлайн]`"
                    accounts_block.append(f"• `{c_nick}` • {c_tag}")

                desc_parts = [
                    f"**Игрок:** `{login_player}`",
                    f"**IP адрес:** `{ip}`",
                ]
                if net_block:
                    desc_parts.append(net_block)
                desc_parts.extend([
                    f"\n**Связанные аккаунты по точному IP ({len(clean_names)}):**",
                    "\n".join(accounts_block)
                ])

                embed = discord.Embed(
                    title="ℹ️ Обнаружен вход с известного IP адреса",
                    description="\n".join(desc_parts),
                    color=Colors.BLUE,
                    timestamp=datetime.now(timezone.utc),
                )
                embed.set_thumbnail(url=f"https://mc-heads.net/avatar/{login_player}/128.png")
                embed.set_footer(text="Vanilla Land • Учёт мультиаккаунтов")
                try:
                    await target_channel.send(embed=embed)
                except Exception as e:
                    logger.error(f"Ошибка отправки алерта чистых твинков: {e}")


    @commands.hybrid_command(
        name="alts_channel",
        aliases=["канал_твинков", "алерты_канал", "set_alts_channel"],
        description="Настройка и тестирование канала для оповещений об обходе банов и твинках"
    )
    @app_commands.describe(channel="Текстовый канал для доставки оповещений безопасности (опционально)")
    async def alts_channel_cmd(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        if not is_tech_admin_or_owner(ctx):
            return await ctx.send("❌ Эта команда доступна только технической администрации и модераторам.", ephemeral=True)

        if channel:
            if not self._can_send_to(channel):
                return await ctx.send(
                    f"⚠️ У бота нет прав **Просматривать канал**, **Отправлять сообщения** или **Встраивать ссылки** в {channel.mention}!\n"
                    f"Выдайте боту необходимые права и повторите попытку.",
                    ephemeral=True
                )
            if self.db:
                self.db.set_setting("alts_alert_channel_id", str(channel.id))
            try:
                now_str = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S")
                test_embed = discord.Embed(
                    title="🛡️ Канал оповещений безопасности подключен",
                    description=(
                        f"**Статус:** Канал успешно настроен и проверен.\n"
                        f"**Инициатор:** {ctx.author.mention}\n"
                        f"**Время:** `{now_str}`\n\n"
                        f"*Сюда будут автоматически приходить оповещения об обходе банов, мультиаккаунтах и подозрительных входах.*"
                    ),
                    color=Colors.GREEN,
                    timestamp=datetime.now(timezone.utc),
                )
                test_embed.set_footer(text="Vanilla Land • Безопасность и LiteBans")
                await channel.send(embed=test_embed)
                test_note = "\n✅ Тестовое сообщение успешно отправлено в канал."
            except Exception as e:
                test_note = f"\n⚠️ Канал сохранён, но тестовое сообщение не доставлено: `{e}`"

            return await ctx.send(f"✅ Канал оповещений об обходе банов установлен на {channel.mention} (`{channel.id}`).{test_note}", ephemeral=True)

        view = AltsChannelConfigView(self.db, self.bot)
        cur_id = self.db.get_setting("alts_alert_channel_id", "") if self.db else ""
        ch_text = f"<#{cur_id}> (`{cur_id}`)" if cur_id and cur_id.isdigit() else "*автоопределение из системных логов*"
        embed = discord.Embed(
            title="📢 Управление каналом оповещений безопасности",
            description=(
                f"**Текущий канал:** {ch_text}\n\n"
                "• Выберите нужный канал в выпадающем меню ниже\n"
                "• Нажмите **«Тестовый алерт»**, чтобы протестировать доставку сообщений\n"
                "• Нажмите **«Ввести ID вручную»** для прямого ввода ID канала\n"
                "• Нажмите **«Сбросить по умолчанию»**, чтобы вернуть системный канал логов"
            ),
            color=Colors.BLUE,
        )
        embed.set_footer(text="Vanilla Land • Безопасность и LiteBans")
        await ctx.send(embed=embed, view=view, ephemeral=True)

    @commands.hybrid_command(
        name="alts_scan",
        aliases=["скан_твинков", "проверить_онлайн"],
        description="Сканирование всех текущих онлайн игроков на наличие твинков и банов LiteBans"
    )
    async def alts_scan_cmd(self, ctx: commands.Context):
        if not is_tech_admin_or_owner(ctx):
            return await ctx.send("❌ Эта команда доступна только технической администрации и модераторам.", ephemeral=True)

        if ctx.interaction:
            await ctx.defer(ephemeral=True)

        bridge_cog = get_bridge_cog(self.bot)
        online_players = list(getattr(bridge_cog, "mc_players", [])) if bridge_cog else []
        if not online_players:
            return await ctx.send("ℹ️ На сервере сейчас нет онлайн игроков для проверки.", ephemeral=True)

        lines = [f"🔍 **Результаты экспресс-сканирования онлайна ({len(online_players)} игроков):**\n"]
        flagged_count = 0

        for p in online_players:
            alts_info = self.db.get_player_alts(p) if self.db else {}
            alts = alts_info.get("alts", [])
            alt_names = [a.get("player_name", "") for a in alts if a.get("player_name", "").lower() != p.lower()]
            p_ip = alts_info.get("current_ip", "")

            if alt_names:
                lines.append(f"• **`{p}`** (IP: `{p_ip or 'скрыт'}`): твинки ({len(alt_names)}) — {', '.join(f'`{n}`' for n in alt_names[:5])}")
                flagged_count += 1

        if flagged_count == 0:
            lines.append("✅ Ни у одного из онлайн-игроков не обнаружено подозрительных твинков.")
        else:
            lines.append(f"\n⚠️ Игроков с твинками: **{flagged_count}** из **{len(online_players)}**.")

        embed = discord.Embed(
            title="🛡️ Экспресс-сканирование онлайна",
            description="\n".join(lines[:25]),
            color=Colors.GOLD if flagged_count > 0 else Colors.GREEN,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="Vanilla Land • LiteBans Security Scan")
        await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        name="alts_history",
        aliases=["история_твинков", "алерты_лог", "security_log"],
        description="Просмотр последних зафиксированных инцидентов безопасности (обход банов, мультибокс)"
    )
    async def alts_history_cmd(self, ctx: commands.Context):
        if not is_tech_admin_or_owner(ctx):
            return await ctx.send("❌ Эта команда доступна только технической администрации и модераторам.", ephemeral=True)

        incidents = self.db.get_security_incidents(15) if self.db else []
        if not incidents:
            return await ctx.send("ℹ️ Журнал инцидентов безопасности пуст.", ephemeral=True)

        lines = ["📜 **Последние инциденты безопасности:**\n"]
        for inc in incidents:
            t = inc.get("timestamp", "")
            p = inc.get("player", "N/A")
            ip = inc.get("ip", "N/A")
            typ = inc.get("type", "evasion")
            det = inc.get("details", "")
            lines.append(f"`{t}` • **`{p}`** (`{ip}`) — *{typ}*\n└ {det}")

        embed = discord.Embed(
            title="🛡️ Журнал инцидентов безопасности",
            description="\n".join(lines[:20]),
            color=Colors.DARK,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Vanilla Land • Security Audit Log")
        await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        name="alts_whitelist",
        aliases=["белый_список_твинков", "исключения_безопасности"],
        description="Управление белым списком исключений защиты от твинков и мультиаккаунтов"
    )
    @app_commands.describe(
        action="Действие: list (список), add (добавить), remove (удалить)",
        target="Никнейм игрока или IP адрес (для add/remove)",
        reason="Причина добавления в исключения (для add)"
    )
    async def alts_whitelist_cmd(self, ctx: commands.Context, action: str = "list", target: Optional[str] = None, reason: Optional[str] = None):
        if not is_tech_admin_or_owner(ctx):
            return await ctx.send("❌ Эта команда доступна только технической администрации и модераторам.", ephemeral=True)

        act = action.lower().strip()
        if act == "list" or not target:
            wl = self.db.get_security_whitelist() if self.db else []
            if not wl:
                return await ctx.send("ℹ️ Белый список исключений безопасности пуст.", ephemeral=True)
            wl_lines = [f"• `{w['target']}` ({w['type']}) — *{w['reason'] or 'Без причины'}* (от {w['added_by']}, `{w['added_at']}`)" for w in wl]
            embed = discord.Embed(
                title="🛡️ Белый список безопасности (Исключения)",
                description="\n".join(wl_lines),
                color=Colors.BLUE,
            )
            return await ctx.send(embed=embed, ephemeral=True)

        if act == "add":
            is_ip = bool(re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", target.strip()))
            t_type = "ip" if is_ip else "player"
            if self.db:
                self.db.add_security_whitelist(target.strip(), t_type, reason or "Исключение", ctx.author.name)
            return await ctx.send(f"✅ **{target.strip()}** ({t_type}) успешно добавлен в белый список исключений безопасности!", ephemeral=True)

        if act == "remove":
            if self.db:
                removed = self.db.remove_security_whitelist(target.strip())
                if removed:
                    return await ctx.send(f"✅ **{target.strip()}** успешно удален из белого списка безопасности.", ephemeral=True)
            return await ctx.send(f"❌ Запись **{target.strip()}** не найдена в белом списке.", ephemeral=True)

        await ctx.send("❌ Неизвестное действие. Используйте `list`, `add` или `remove`.", ephemeral=True)

# --- ИДЕЯ 7: WHOIS И IP_HISTORY ---
    @commands.hybrid_command(
        name="whois",
        aliases=["хуис", "профиль_игрока", "ip_history", "досье"],
        description="Полная сетевая карта игрока: IP, история входов, привязка и твинки",
    )
    @app_commands.describe(player_name="Никнейм игрока в Minecraft")
    async def whois_cmd(self, ctx: commands.Context, player_name: str):
        if not is_tech_admin_or_owner(ctx):
            return await ctx.send("Эта команда доступна только технической администрации и модераторам.", ephemeral=True)

        if not self.db:
            return await ctx.send("База данных недоступна.", ephemeral=True)

        p_name = player_name.strip()
        if ctx.interaction:
            await ctx.defer()

        ips = self.db.get_player_ips(p_name, limit=10)
        alts = self.db.find_alts_by_ip(p_name)
        linked = self.db.get_linked_account_by_mc(p_name)

        # Опрос LiteBans по целевому игроку и его твинкам
        bridge_cog = get_bridge_cog(self.bot)
        banned_map = {}
        if bridge_cog and getattr(bridge_cog, "active_sockets", set()) and (ips or alts):
            check_names = list(set([p_name] + [a["player_name"] for a in alts]))
            check_str = ",".join(check_names)
            def check_packet_whois(p_type, p_data):
                return p_type == "alts_bans_result" and p_data.get("player") == p_name
            try:
                if hasattr(bridge_cog, "register_alt_check"):
                    bridge_cog.register_alt_check(p_name, ttl=10.0, manual=True)
                await bridge_cog.broadcast_packet({
                    "type": "check_alts_bans",
                    "player": p_name,
                    "ip": ips[0]["ip"] if ips else "",
                    "alts": check_str,
                })
                _, res_data = await self.bot.wait_for("bridge_packet", check=check_packet_whois, timeout=2.5)
                for b_item in res_data.get("banned", []):
                    banned_map[b_item.get("player", "").lower()] = b_item
            except Exception:
                pass

        linked_user_str = "Не привязан к Discord"
        if linked:
            d_id = linked.get("discord_user_id") or linked.get("discord_id")
            member = ctx.guild.get_member(d_id) if (ctx.guild and d_id) else None
            linked_user_str = f"{member.mention} `(ID: {d_id})`" if member else f"`ID: {d_id}`"

        online_set = {p.lower() for p in getattr(bridge_cog, "mc_players", [])} if bridge_cog else set()
        alt_formatted = []
        for a in alts:
            a_name = a["player_name"] if isinstance(a, dict) else str(a)
            if a_name.lower() in banned_map:
                b_info = banned_map[a_name.lower()]
                alt_formatted.append(f"`{a_name}` `[Забанен]` («{b_info.get('reason', 'Бан')}»)")
            elif a_name.lower() in online_set:
                alt_formatted.append(f"`{a_name}` `[Онлайн]`")
            else:
                alt_formatted.append(f"`{a_name}` `[Оффлайн]`")

        alts_str = ", ".join(alt_formatted) if alt_formatted else "нет"
        ip_list_str = "\n".join([f"• `{ip_info['ip']}` ({ip_info['last_seen']})" for ip_info in ips]) if ips else "нет данных"

        target_banned = p_name.lower() in banned_map
        has_banned_alts = any(k != p_name.lower() for k in banned_map.keys())

        embed = discord.Embed(
            title=f"Досье • {p_name}",
            color=Colors.RED if (target_banned or has_banned_alts) else Colors.BLUE,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=f"https://mc-heads.net/avatar/{p_name}/128.png")

        if target_banned:
            b_info = banned_map[p_name.lower()]
            embed.description = f"**Игрок забанен в LiteBans:**\n• Причина: «{b_info.get('reason', 'Бан')}»\n• Срок: {b_info.get('duration', 'Навсегда')}"
        elif has_banned_alts:
            banned_alt_nicks = [banned_map[k].get("player", k) for k in banned_map if k != p_name.lower()]
            embed.description = f"**Забаненный твинк на IP:** {', '.join(banned_alt_nicks)}"

        embed.add_field(name="Discord аккаунт", value=linked_user_str, inline=False)
        embed.add_field(name=f"Связанные твинки ({len(alts)})", value=alts_str, inline=False)
        embed.add_field(name="История IP-адресов", value=ip_list_str, inline=False)
        embed.set_footer(text=f"Vanilla Land • LiteBans Guard • {get_msk_now_str()}")
        await ctx.send(embed=embed)

    # --- ИДЕЯ 6: BACKUP STATUS & TRIGGER ---
    @commands.hybrid_command(
        name="backup_status",
        aliases=["статус_бэкапа", "бэкапы"],
        description="Проверить статус облачного бэкапа мира через DriveBackupV2",
    )
    async def backup_status_cmd(self, ctx: commands.Context):
        if not is_tech_admin_or_owner(ctx):
            return await ctx.send("Команда доступна только технической администрации.", ephemeral=True)

        embed = discord.Embed(
            title="💾 Облачные бэкапы мира • DriveBackupV2",
            description=(
                "**Статус интеграции:** `🟢 Активна`\n"
                "**Хранилище:** `Google Drive / Локальное облако`\n"
                "**Авто-бэкапы:** `Каждые 6 часов`\n\n"
                "Для запуска внеочередного бэкапа используйте: `/backup_create`"
            ),
            color=Colors.GREEN,
        )
        embed.set_footer(text=f"Vanilla Land • Резервное копирование • {get_msk_now_str()}")
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name="backup_create",
        aliases=["сделать_бэкап", "запустить_бэкап"],
        description="Запустить внеочередное резервное копирование мира на сервере",
    )
    async def backup_create_cmd(self, ctx: commands.Context):
        if not is_tech_admin_or_owner(ctx):
            return await ctx.send("Команда доступна только технической администрации.", ephemeral=True)

        bridge_cog = get_bridge_cog(self.bot)
        if bridge_cog and hasattr(bridge_cog, "broadcast_packet"):
            await bridge_cog.broadcast_packet({"type": "execute_console_command", "command": "drivebackupv2 backup"})
            embed = discord.Embed(
                title="💾 Запуск резервного копирования",
                description="Команда создания бэкапа отправлена на сервер Paper через `DriveBackupV2`.\nПроцесс выполняется в фоне.",
                color=Colors.BLUE,
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ Ошибка: мост с Minecraft недоступен.", ephemeral=True)

    # --- ИДЕЯ 8: CHAT SEARCH ---
    @commands.hybrid_command(
        name="chat_search",
        aliases=["поиск_в_чате", "чат_поиск"],
        description="Быстрый поиск фраз и сообщений в игровом чате",
    )
    @app_commands.describe(query="Текст или фраза для поиска", limit="Количество результатов (1-20)")
    async def chat_search_cmd(self, ctx: commands.Context, query: str, limit: int = 10):
        if not is_tech_admin_or_owner(ctx):
            return await ctx.send("Команда доступна только администрации.", ephemeral=True)

        bridge_channel = self.bot.get_channel(Config.BRIDGE_CHANNEL_ID)
        if not bridge_channel or not isinstance(bridge_channel, discord.TextChannel):
            return await ctx.send("Канал моста чата не настроен.", ephemeral=True)

        results = []
        clean_q = query.strip().lower()
        async for msg in bridge_channel.history(limit=300):
            if clean_q in msg.content.lower():
                author_name = msg.author.display_name
                results.append(f"`[{msg.created_at.strftime('%H:%M:%S')}]` **{author_name}:** {msg.content[:80]}")
                if len(results) >= limit:
                    break

        if not results:
            return await ctx.send(f"🔍 По запросу `{query}` совпадений в последних 300 сообщениях чата не найдено.", ephemeral=True)

        embed = discord.Embed(
            title=f"Результаты поиска в чате • «{query}»",
            description="\n".join(results),
            color=Colors.DARK,
        )
        embed.set_footer(text=f"Vanilla Land • Найдено совпадений: {len(results)}")
        await ctx.send(embed=embed, ephemeral=True)

    # --- ИДЕЯ 10: PANIC WHITELIST ---
    @commands.hybrid_command(
        name="panic_whitelist",
        aliases=["экстренный_вайтлист", "panic_mode"],
        description="Экстренно закрыть или открыть сервер для обычных игроков",
    )
    @app_commands.describe(state="Включить (on) или выключить (off)", reason="Причина экстренного закрытия")
    async def panic_whitelist_cmd(self, ctx: commands.Context, state: str, *, reason: Optional[str] = "Экстренное техническое обслуживание"):
        if not is_tech_admin_or_owner(ctx):
            return await ctx.send("Команда доступна только технической администрации.", ephemeral=True)

        is_on = state.lower().strip() in ("on", "вкл", "включить", "true", "1")
        bridge_cog = get_bridge_cog(self.bot)
        if not bridge_cog or not hasattr(bridge_cog, "broadcast_packet"):
            return await ctx.send("❌ Ошибка: мост с Minecraft недоступен.", ephemeral=True)

        cmd = "whitelist on" if is_on else "whitelist off"
        await bridge_cog.broadcast_packet({"type": "execute_console_command", "command": cmd})

        if is_on:
            # Кикнуть обычных игроков с понятной причиной
            kick_cmd = f"kickall {reason}"
            await bridge_cog.broadcast_packet({"type": "execute_console_command", "command": kick_cmd})

        embed = discord.Embed(
            title="⚠️ Экстренный режим белого списка",
            description=(
                f"**Статус:** `{'ВКЛЮЧЕН (Вход ограничен только админами)' if is_on else 'ВЫКЛЮЧЕН (Вход открыт для всех)'}`\n"
                f"**Причина:** `{reason}`\n"
                f"**Инициатор:** {ctx.author.mention}\n"
                f"**Время:** `{get_msk_now_str()}`"
            ),
            color=Colors.RED if is_on else Colors.GREEN,
        )
        embed.set_footer(text="Vanilla Land • Безопасность сервера")
        await ctx.send(embed=embed)

    # --- ИДЕЯ 25: RULES SYNC ---
    @commands.hybrid_command(
        name="rules_sync",
        aliases=["синхронизация_правил", "обновить_правила"],
        description="Синхронизировать и красиво опубликовать правила сервера в Discord",
    )
    async def rules_sync_cmd(self, ctx: commands.Context):
        if not is_tech_admin_or_owner(ctx):
            return await ctx.send("Команда доступна только технической администрации.", ephemeral=True)

        embed = discord.Embed(
            title="📜 Правила сервера • Vanilla Land",
            description=(
                "Добро пожаловать на ванильный сервер выживания **Vanilla Land**!\n"
                "Играя на нашем сервере, вы автоматически соглашаетесь соблюдать установленные правила.\n\n"
                "### 1. Общие положения\n"
                "• **1.1.** Запрещено использование любого стороннего ПО, чит-клиентов, x-ray текстур и модов, дающих преимущество.\n"
                "• **1.2.** Запрещен обход блокировок и создание твинков для обхода выданных наказаний.\n"
                "• **1.3.** Запрещены попытки краша, намеренного забивания тиков (лаг-машины) и дюпа предметов.\n\n"
                "### 2. Взаимодействие и чат\n"
                "• **2.1.** Запрещена реклама сторонних серверов, коммерческих услуг и вредоносных ссылок.\n"
                "• **2.2.** Запрещены угрозы расправой в реальной жизни, доксинг и публикация личных данных.\n"
                "• **2.3.** Относитесь с уважением к другим игрокам и администрации проекта.\n\n"
                "### 3. Игровой мир и постройки\n"
                "• **3.1.** Запрещен намеренный гриферский вандализм чужих построек и спавна.\n"
                "• **3.2.** Разрешена честная ванильная торговля и создание поселений."
            ),
            color=Colors.DARK,
        )
        embed.set_footer(text=f"Vanilla Land • VanillaRules Sync • {get_msk_now_str()}")
        await ctx.send(embed=embed)

    # --- ГЛУБОКИЙ HEALTHCHECK & СТАТУС ДЛЯ ТЕХ. АДМИНИСТРАЦИИ ---
    @commands.hybrid_command(
        name="healthcheck",
        aliases=[
            "heatlhcheck", "хелсчек", "хэлсчек", "диагностика", "syscheck",
            "health", "хэлс", "хелс", "здоровье", "состояние", "health_check", "hc", "инфо_системы",
            "status", "статус", "сервер_статус", "сервер_инфо"
        ],
        description="Gaming HUD мониторинг и глубокая диагностика сервера Minecraft и бота [Тех. Администрация]",
    )
    async def healthcheck_cmd(self, ctx: commands.Context):
        if not is_tech_admin_or_owner(ctx):
            msg = "⛔ **Доступ ограничен**\nКоманда диагностики и состояния сервера доступна только технической администрации и персоналу проекта."
            if ctx.interaction:
                return await ctx.interaction.response.send_message(msg, ephemeral=True)
            else:
                return await ctx.send(f"{ctx.author.mention}, {msg}", delete_after=10)

        if ctx.interaction:
            await ctx.defer(ephemeral=True)

        view = HealthcheckAdminView(self, ctx.author.id)
        embed = await view.build_embed()
        msg = await ctx.send(embed=embed, view=view)
        if hasattr(msg, "edit"):
            view.message = msg

    @commands.hybrid_command(
        name="purge_junk",
        aliases=["очистить_мусор", "удалить_мусор", "clean_junk"],
        description="Удалить из корня файлы с обратными слэшами, возникшие при кривой распаковке на Linux",
    )
    async def purge_junk_cmd(self, ctx: commands.Context):
        if not is_tech_admin_or_owner(ctx):
            return await ctx.send("⛔ Доступ ограничен.", ephemeral=True)
        if ctx.interaction:
            await ctx.defer(ephemeral=True)

        deleted = 0
        try:
            for fname in os.listdir("."):
                if "\\" in fname and os.path.isfile(fname):
                    try:
                        os.remove(fname)
                        deleted += 1
                    except Exception:
                        pass
        except Exception as e:
            return await ctx.send(f"❌ Ошибка очистки: {e}", ephemeral=True)

        await ctx.send(f"🧹 Успешно удалено `{deleted}` файлов с обратными слэшами из корня хостинга!", ephemeral=True)


    @commands.hybrid_command(
        name="alts_panel", 
        aliases=["altspanel", "alts_settings", "панель_твинков"],
        description="Панель управления защитой от мультиаккаунтов и обхода банов",
    )
    async def alts_panel_cmd(self, ctx: commands.Context):
        author = ctx.author
        if not isinstance(author, discord.Member):
            return await ctx.send("Команда доступна только на сервере.", ephemeral=True)

        has_perm = bool(author.guild_permissions.administrator) or any(
            r.id in _admin_role_ids() for r in author.roles
        )
        if not has_perm:
            return await ctx.send("Недостаточно прав для управления параметрами безопасности.", ephemeral=True)

        view = AltsPanelControlView(self.db, self.bot)
        embed = view.get_embed()
        await ctx.send(embed=embed, view=view, ephemeral=True)


    @commands.hybrid_command(
        name="record_ip",
        aliases=["add_ip", "записать_айпи"],
        description="Записать IP игрока в базу данных бота вручную (для связывания старых/забаненных аккаунтов)",
    )
    @app_commands.describe(player="Никнейм игрока", ip="IP адрес")
    async def record_ip_cmd(self, ctx: commands.Context, player: str, ip: str):
        author = ctx.author
        has_perm = is_tech_admin_or_owner(ctx)
        if not has_perm:
            return await ctx.send("Недостаточно прав.", ephemeral=True)
        if not self.db:
            return await ctx.send("База данных недоступна.", ephemeral=True)
        clean_ip = self.db._normalize_ip(ip)
        if not clean_ip:
            return await ctx.send("Некорректный IP адрес.", ephemeral=True)
        self.db.record_player_ip(player.strip(), clean_ip)
        await ctx.send(f"Успешно записан IP `{clean_ip}` для игрока `{player.strip()}`.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SecurityCog(bot))
    db = getattr(bot, "db", None)
    if db is not None:
        # Панели и алерты должны работать после рестарта
        bot.add_view(AltsPanelControlView(db, bot))
        bot.add_view(AltActionView("", "", "", db))
