import asyncio
import logging
import re
import secrets
import time
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import app_commands, ui
from discord.ext import commands, tasks

from config import Config
from database import DatabaseManager
from design import Colors

logger = logging.getLogger("VanillaBot.Giveaways")


def is_admin_or_mod(user: discord.abc.User, guild: Optional[discord.Guild]) -> bool:
    if not isinstance(user, discord.Member):
        return False
    if user.guild_permissions.administrator or (guild and user.id == guild.owner_id):
        return True
    role_ids = {r.id for r in user.roles}
    return any(rid in role_ids for rid in Config.MOD_ROLE_IDS)


def parse_giveaway_duration(raw: str) -> Optional[int]:
    """Парсит длительность вида '30m', '2h', '1d', '1д 12ч' в секунды."""
    text = str(raw or "").strip().lower()
    if not text:
        return None
    if text.isdigit():
        return max(60, int(text) * 60)

    total = 0
    for val_s, unit in re.findall(r"(\d+)\s*([a-zа-яё]+)", text):
        val = int(val_s)
        if unit.startswith(("s", "с")):
            total += val
        elif unit.startswith(("m", "м")):
            total += val * 60
        elif unit.startswith(("h", "ч")):
            total += val * 3600
        elif unit.startswith(("d", "д")):
            total += val * 86400
        elif unit.startswith(("w", "н")):
            total += val * 604800
    return total if total >= 60 else None


def build_giveaway_embed(gw: dict, entries_count: int) -> discord.Embed:
    is_ended = gw.get("status") == "ended"
    end_ts = int(gw.get("end_timestamp", time.time()))
    desc_parts = []
    if gw.get("description"):
        desc_parts.append(gw["description"])
        desc_parts.append("")

    if is_ended:
        winners = gw.get("winners", [])
        if winners:
            win_str = ", ".join(f"<@{w}>" for w in winners)
            desc_parts.append(f"**Победители:** {win_str}")
        else:
            desc_parts.append("**Победители:** недостаточно участников")
    else:
        desc_parts.append("Нажмите кнопку **«Участвовать»** ниже, чтобы присоединиться к розыгрышу.")

    embed = discord.Embed(
        title=f"Розыгрыш • {gw['prize']}",
        description="\n".join(desc_parts),
        color=Colors.DARK if is_ended else Colors.GOLD,
        timestamp=datetime.fromtimestamp(end_ts, tz=timezone.utc),
    )
    embed.add_field(name="Приз", value=f"**{gw['prize']}**", inline=True)
    embed.add_field(name="Победителей", value=f"`{gw['winners_count']}`", inline=True)
    embed.add_field(name="Участников", value=f"`{entries_count}`", inline=True)
    embed.add_field(
        name="Завершение" if not is_ended else "Завершён",
        value=f"<t:{end_ts}:R> (<t:{end_ts}:f>)",
        inline=True,
    )
    embed.add_field(name="Организатор", value=f"<@{gw['host_id']}>", inline=True)
    embed.set_footer(text=f"Vanilla Land • Розыгрыш #{gw['id']} • {'Завершён' if is_ended else 'Активен'}")
    return embed


class GiveawaySetupModal(ui.Modal, title="Параметры розыгрыша"):
    prize_input = ui.TextInput(
        label="Приз",
        placeholder="Например: Привилегия на 30 дней или 500 алмазов",
        max_length=150,
        required=True,
    )
    duration_input = ui.TextInput(
        label="Длительность (например: 30m, 2h, 1d, 3d)",
        placeholder="1d",
        default="1d",
        max_length=32,
        required=True,
    )
    winners_input = ui.TextInput(
        label="Количество победителей",
        placeholder="1",
        default="1",
        max_length=3,
        required=True,
    )
    desc_input = ui.TextInput(
        label="Описание / дополнительные условия",
        style=discord.TextStyle.paragraph,
        placeholder="Необязательно: условия выдачи приза и детали...",
        max_length=1000,
        required=False,
    )

    def __init__(self, builder_view: "GiveawayBuilderView"):
        super().__init__()
        self.builder_view = builder_view
        if builder_view.prize:
            self.prize_input.default = builder_view.prize
        if builder_view.duration_raw:
            self.duration_input.default = builder_view.duration_raw
        self.winners_input.default = str(builder_view.winners_count)
        if builder_view.description:
            self.desc_input.default = builder_view.description

    async def on_submit(self, interaction: discord.Interaction):
        dur_sec = parse_giveaway_duration(self.duration_input.value)
        if not dur_sec:
            return await interaction.response.send_message(
                "Некорректная длительность. Укажите минимум 1 минуту, например: `30m`, `2h`, `1d`.",
                ephemeral=True,
            )
        w_raw = (self.winners_input.value or "1").strip()
        if not w_raw.isdigit() or int(w_raw) < 1 or int(w_raw) > 25:
            return await interaction.response.send_message(
                "Количество победителей должно быть от 1 до 25.",
                ephemeral=True,
            )

        self.builder_view.prize = self.prize_input.value.strip()
        self.builder_view.duration_raw = self.duration_input.value.strip()
        self.builder_view.duration_sec = dur_sec
        self.builder_view.winners_count = int(w_raw)
        self.builder_view.description = (self.desc_input.value or "").strip()
        self.builder_view.sync_controls()

        await interaction.response.edit_message(embed=self.builder_view.build_preview_embed(), view=self.builder_view)


class GiveawayBuilderView(ui.View):
    """Интерактивный GUI-конструктор розыгрыша с предпросмотром и отправкой."""

    def __init__(self, cog: "GiveawaysCog", host: discord.Member, default_channel: discord.TextChannel):
        super().__init__(timeout=300)
        self.cog = cog
        self.host = host
        self.target_channel: discord.TextChannel = default_channel
        self.prize: str = ""
        self.description: str = ""
        self.duration_raw: str = "1d"
        self.duration_sec: int = 86400
        self.winners_count: int = 1
        self.sync_controls()

    def sync_controls(self):
        self.btn_launch.disabled = not bool(self.prize)

    def build_preview_embed(self) -> discord.Embed:
        end_ts = int(time.time() + self.duration_sec)
        prize_label = self.prize if self.prize else "*Не задан (нажмите «Настроить приз и условия»)*"
        embed = discord.Embed(
            title="Конструктор розыгрыша • Vanilla Land",
            description=(
                f"{self.description}\n\n" if self.description else ""
            ) + "Настройте параметры, выберите канал и нажмите **«Запустить и отправить»**.",
            color=Colors.INDIGO,
        )
        embed.add_field(name="Приз", value=prize_label, inline=True)
        embed.add_field(name="Победителей", value=f"`{self.winners_count}`", inline=True)
        embed.add_field(name="Длительность", value=f"`{self.duration_raw}` (<t:{end_ts}:R>)", inline=True)
        embed.add_field(name="Канал отправки", value=self.target_channel.mention, inline=True)
        embed.set_footer(text="Vanilla Land • Предпросмотр розыгрыша")
        return embed

    @ui.button(label="Настроить приз и условия", style=discord.ButtonStyle.primary, row=0)
    async def btn_setup(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.host.id:
            return await interaction.response.send_message("Этот конструктор открыт другим администратором.", ephemeral=True)
        await interaction.response.send_modal(GiveawaySetupModal(self))

    @ui.select(
        cls=ui.ChannelSelect,
        placeholder="Выбрать канал для отправки розыгрыша...",
        channel_types=[discord.ChannelType.text],
        min_values=1,
        max_values=1,
        row=1,
    )
    async def sel_channel(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        if interaction.user.id != self.host.id:
            return await interaction.response.send_message("Этот конструктор открыт другим администратором.", ephemeral=True)
        if select.values:
            ch = interaction.guild.get_channel(select.values[0].id) if interaction.guild else None
            if isinstance(ch, discord.TextChannel):
                self.target_channel = ch
        await interaction.response.edit_message(embed=self.build_preview_embed(), view=self)

    @ui.button(label="Запустить и отправить", style=discord.ButtonStyle.success, row=2)
    async def btn_launch(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.host.id:
            return await interaction.response.send_message("Этот конструктор открыт другим администратором.", ephemeral=True)
        if not self.prize:
            return await interaction.response.send_message("Сначала укажите приз.", ephemeral=True)

        if not interaction.guild:
            return await interaction.response.send_message("Розыгрыш можно запустить только на сервере.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        end_ts = time.time() + self.duration_sec
        gw_id = await asyncio.to_thread(
            self.cog.db.create_giveaway,
            interaction.guild.id,
            self.target_channel.id,
            self.prize,
            self.description,
            self.winners_count,
            end_ts,
            False,
            self.host.id,
        )
        gw = await asyncio.to_thread(self.cog.db.get_giveaway, gw_id)
        if not gw:
            return await interaction.followup.send("Не удалось создать запись розыгрыша в БД.", ephemeral=True)

        pub_view = GiveawayPublicView(self.cog.db, entries_count=0, ended=False)
        pub_embed = build_giveaway_embed(gw, 0)
        try:
            sent_msg = await self.target_channel.send(embed=pub_embed, view=pub_view)
        except discord.Forbidden:
            return await interaction.followup.send(
                f"У бота нет прав на отправку сообщений в {self.target_channel.mention}.",
                ephemeral=True,
            )
        except Exception as e:
            return await interaction.followup.send(f"Ошибка отправки розыгрыша: {e}", ephemeral=True)

        await asyncio.to_thread(self.cog.db.set_giveaway_message_id, gw_id, sent_msg.id)
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        await interaction.edit_original_response(
            content=f"Розыгрыш **#{gw_id}** запущен и отправлен в {self.target_channel.mention}.",
            embed=pub_embed,
            view=self,
        )

    @ui.button(label="Отмена", style=discord.ButtonStyle.danger, row=2)
    async def btn_cancel(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.host.id:
            return await interaction.response.send_message("Этот конструктор открыт другим администратором.", ephemeral=True)
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        await interaction.response.edit_message(content="Создание розыгрыша отменено.", embed=None, view=self)


class GiveawayAdminManageView(ui.View):
    """Панель управления розыгрышем для администратора."""

    def __init__(self, cog: "GiveawaysCog", giveaway_id: int):
        super().__init__(timeout=120)
        self.cog = cog
        self.giveaway_id = giveaway_id

    @ui.button(label="Завершить сейчас", style=discord.ButtonStyle.danger)
    async def btn_end_now(self, interaction: discord.Interaction, button: ui.Button):
        if not is_admin_or_mod(interaction.user, interaction.guild):
            return await interaction.response.send_message("Недостаточно прав.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        winners = await self.cog.finalize_giveaway(self.giveaway_id, force=True)
        if winners is None:
            return await interaction.followup.send("Розыгрыш не найден.", ephemeral=True)
        await interaction.followup.send(f"Розыгрыш #{self.giveaway_id} завершён.", ephemeral=True)

    @ui.button(label="Перевыбрать победителей", style=discord.ButtonStyle.primary)
    async def btn_reroll(self, interaction: discord.Interaction, button: ui.Button):
        if not is_admin_or_mod(interaction.user, interaction.guild):
            return await interaction.response.send_message("Недостаточно прав.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        winners = await self.cog.reroll_giveaway(self.giveaway_id)
        if not winners:
            return await interaction.followup.send("Не удалось перевыбрать: нет участников или розыгрыш не найден.", ephemeral=True)
        win_str = ", ".join(f"<@{w}>" for w in winners)
        await interaction.followup.send(f"Новые победители розыгрыша #{self.giveaway_id}: {win_str}", ephemeral=True)


class GiveawayPublicView(ui.View):
    """Постоянные кнопки публичного сообщения розыгрыша."""

    def __init__(self, db: DatabaseManager, entries_count: int = 0, ended: bool = False):
        super().__init__(timeout=None)
        self.db = db
        self.btn_join.label = f"Участвовать ({entries_count})"
        self.btn_join.disabled = ended

    @ui.button(label="Участвовать (0)", style=discord.ButtonStyle.success, custom_id="giveaway:join")
    async def btn_join(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.message:
            return await interaction.response.send_message("Сообщение розыгрыша не найдено.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)

        gw = await asyncio.to_thread(self.db.get_giveaway_by_message, interaction.message.id)
        if not gw:
            return await interaction.followup.send("Розыгрыш не найден в базе данных.", ephemeral=True)
        if gw["status"] != "active" or time.time() >= gw["end_timestamp"]:
            return await interaction.followup.send("Этот розыгрыш уже завершён.", ephemeral=True)

        joined, total = await asyncio.to_thread(self.db.toggle_giveaway_entry, gw["id"], interaction.user.id)
        new_view = GiveawayPublicView(self.db, entries_count=total, ended=False)
        try:
            await interaction.message.edit(embed=build_giveaway_embed(gw, total), view=new_view)
        except Exception as e:
            logger.debug("Не удалось обновить карточку розыгрыша #%s: %s", gw["id"], e)

        if joined:
            await interaction.followup.send(f"Вы участвуете в розыгрыше «{gw['prize']}».", ephemeral=True)
        else:
            await interaction.followup.send(f"Вы вышли из розыгрыша «{gw['prize']}».", ephemeral=True)

    @ui.button(label="Участники", style=discord.ButtonStyle.secondary, custom_id="giveaway:participants")
    async def btn_participants(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.message:
            return
        await interaction.response.defer(ephemeral=True)
        gw = await asyncio.to_thread(self.db.get_giveaway_by_message, interaction.message.id)
        if not gw:
            return await interaction.followup.send("Розыгрыш не найден.", ephemeral=True)
        entries = await asyncio.to_thread(self.db.get_giveaway_entries, gw["id"])
        if not entries:
            return await interaction.followup.send("Пока никто не участвует.", ephemeral=True)
        preview = ", ".join(f"<@{uid}>" for uid in entries[:40])
        if len(entries) > 40:
            preview += f" и ещё {len(entries) - 40}"
        await interaction.followup.send(f"Всего участников: **{len(entries)}**\n{preview}", ephemeral=True)

    @ui.button(label="Управление", style=discord.ButtonStyle.secondary, custom_id="giveaway:manage")
    async def btn_manage(self, interaction: discord.Interaction, button: ui.Button):
        if not is_admin_or_mod(interaction.user, interaction.guild):
            return await interaction.response.send_message("Доступно только администрации.", ephemeral=True)
        if not interaction.message:
            return
        gw = await asyncio.to_thread(self.db.get_giveaway_by_message, interaction.message.id)
        if not gw:
            return await interaction.response.send_message("Розыгрыш не найден.", ephemeral=True)
        cog = interaction.client.get_cog("Розыгрыши")
        if not isinstance(cog, GiveawaysCog):
            return await interaction.response.send_message("Модуль розыгрышей не активен.", ephemeral=True)
        await interaction.response.send_message(
            f"Управление розыгрышем **#{gw['id']}** («{gw['prize']}»):",
            view=GiveawayAdminManageView(cog, gw["id"]),
            ephemeral=True,
        )


class GiveawaysCog(commands.Cog, name="Розыгрыши"):
    def __init__(self, bot: commands.Bot, db: DatabaseManager):
        self.bot = bot
        self.db = db
        self.giveaway_loop.start()

    def cog_unload(self):
        self.giveaway_loop.cancel()

    async def finalize_giveaway(self, giveaway_id: int, force: bool = False) -> Optional[list[int]]:
        gw = await asyncio.to_thread(self.db.get_giveaway, giveaway_id)
        if not gw:
            return None
        if gw["status"] == "ended" and not force:
            return gw.get("winners", [])

        entries = await asyncio.to_thread(self.db.get_giveaway_entries, giveaway_id)
        k = min(len(entries), max(1, gw["winners_count"]))
        winners = secrets.SystemRandom().sample(entries, k) if k > 0 else []
        await asyncio.to_thread(self.db.finish_giveaway, giveaway_id, winners)
        gw["status"] = "ended"
        gw["winners"] = winners

        ch = self.bot.get_channel(gw["channel_id"])
        if isinstance(ch, discord.TextChannel):
            if gw["message_id"]:
                try:
                    msg = await ch.fetch_message(gw["message_id"])
                    await msg.edit(
                        embed=build_giveaway_embed(gw, len(entries)),
                        view=GiveawayPublicView(self.db, entries_count=len(entries), ended=True),
                    )
                except Exception as e:
                    logger.debug("Не удалось обновить сообщение розыгрыша #%s: %s", giveaway_id, e)

            if winners:
                win_mentions = ", ".join(f"<@{w}>" for w in winners)
                emb = discord.Embed(
                    title=f"Итоги розыгрыша • {gw['prize']}",
                    description=f"Победители: {win_mentions}\nВсего участников: `{len(entries)}`",
                    color=Colors.GREEN,
                )
            else:
                emb = discord.Embed(
                    title=f"Розыгрыш завершён • {gw['prize']}",
                    description="Победитель не выбран: не было участников.",
                    color=Colors.DARK,
                )
            emb.set_footer(text=f"Vanilla Land • Розыгрыш #{giveaway_id}")
            try:
                await ch.send(content=", ".join(f"<@{w}>" for w in winners) if winners else None, embed=emb)
            except Exception as e:
                logger.warning("Не удалось отправить итоги розыгрыша #%s: %s", giveaway_id, e)
        return winners

    async def reroll_giveaway(self, giveaway_id: int) -> list[int]:
        gw = await asyncio.to_thread(self.db.get_giveaway, giveaway_id)
        if not gw:
            return []
        entries = await asyncio.to_thread(self.db.get_giveaway_entries, giveaway_id)
        if not entries:
            return []
        k = min(len(entries), max(1, gw["winners_count"]))
        winners = secrets.SystemRandom().sample(entries, k)
        await asyncio.to_thread(self.db.finish_giveaway, giveaway_id, winners)
        gw["status"] = "ended"
        gw["winners"] = winners

        ch = self.bot.get_channel(gw["channel_id"])
        if isinstance(ch, discord.TextChannel):
            if gw["message_id"]:
                try:
                    msg = await ch.fetch_message(gw["message_id"])
                    await msg.edit(
                        embed=build_giveaway_embed(gw, len(entries)),
                        view=GiveawayPublicView(self.db, entries_count=len(entries), ended=True),
                    )
                except Exception:
                    pass
            win_mentions = ", ".join(f"<@{w}>" for w in winners)
            try:
                await ch.send(f"Перевыбор победителей розыгрыша **#{giveaway_id}** ({gw['prize']}): {win_mentions}")
            except Exception:
                pass
        return winners

    @tasks.loop(seconds=15)
    async def giveaway_loop(self):
        try:
            active = await asyncio.to_thread(self.db.get_active_giveaways)
        except Exception as e:
            logger.debug("Ошибка чтения активных розыгрышей: %s", e)
            return

        now = time.time()
        for gw in active:
            if gw["end_timestamp"] <= now:
                try:
                    await self.finalize_giveaway(gw["id"])
                except Exception as e:
                    logger.warning("Ошибка завершения розыгрыша #%s: %s", gw["id"], e)

    @giveaway_loop.before_loop
    async def before_giveaway_loop(self):
        await self.bot.wait_until_ready()

    @commands.hybrid_command(
        name="giveaway",
        aliases=["розыгрыш", "конкурс", "gw"],
        description="[Админ] Открыть GUI-конструктор создания и отправки розыгрыша",
    )
    async def giveaway_cmd(self, ctx: commands.Context):
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return await ctx.send("Команда доступна только на сервере.", ephemeral=True)
        if not is_admin_or_mod(ctx.author, ctx.guild):
            return await ctx.send("Эта команда доступна только персоналу сервера.", ephemeral=True)

        default_ch = ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None
        if not default_ch:
            for c in ctx.guild.text_channels:
                default_ch = c
                break
        if not default_ch:
            return await ctx.send("Не найден текстовый канал для отправки.", ephemeral=True)

        view = GiveawayBuilderView(self, ctx.author, default_ch)
        await ctx.send(embed=view.build_preview_embed(), view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    db: DatabaseManager = bot.db
    await bot.add_cog(GiveawaysCog(bot, db))
    bot.add_view(GiveawayPublicView(db))
