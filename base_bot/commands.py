"""
WaterBot - AI Discord bot manager
Copyright (C) 2026  Nerdlabs AI

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

from discord import app_commands, Interaction
import discord
import os
import psutil
import numpy as np
import time
from config import DEBUG, OWNER_ID, NAME
import storage
from memory import delete_user_memories
import metrics

def load_recent_questions():
    return storage.load_recent_questions() or {}

def save_recent_questions(data):
    storage.save_recent_questions(data or {})

def load_daily_quiz_records():
    return storage.load_daily_quiz_records() or {}

def save_daily_quiz_records(data):
    storage.save_daily_quiz_records(data or {})

def cosine(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

def setup(bot):
    config_group = app_commands.Group(name="config", description="Configuration")

    @config_group.command(name="activate", description=f"Make {NAME} respond to all messages in this channel (or disable it)")
    async def activate(interaction: Interaction):
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You must be a server administrator to use this command.", ephemeral=True)
            return
        from bot import load_settings, save_settings
        settings = load_settings()
        sid = str(interaction.guild.id)
        guild_settings = settings.get(sid, {})
        allowed = guild_settings.get("allowed_channels", [])
        chan_id = interaction.channel_id
        if chan_id in allowed:
            allowed.remove(chan_id)
            action = "no longer"
        else:
            permissions = interaction.channel.permissions_for(interaction.guild.me)
            if not permissions.send_messages:
                await interaction.response.send_message("I do not have permission to send messages in this channel.", ephemeral=True)
                return
            allowed.append(chan_id)
            action = "now"
        guild_settings["allowed_channels"] = allowed
        settings[sid] = guild_settings
        save_settings(settings)
        await interaction.response.send_message(
            f"{NAME} will {action} respond to all messages in <#{chan_id}>.",
            ephemeral=False
        )

    @config_group.command(name="natural-replies", description=f"Control how often {NAME} responds without being pinged")
    @app_commands.describe(rate="The frequency of random responses")
    @app_commands.choices(rate=[
        app_commands.Choice(name="Low", value="low"),
        app_commands.Choice(name="Medium", value="mid"),
        app_commands.Choice(name="High", value="high"),
    ])
    async def freewill_rate(interaction: Interaction, rate: str):
        if not interaction.guild:
            return await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("You must be a server administrator to use this command.", ephemeral=True)
        from bot import load_settings, save_settings
        settings = load_settings()
        sid = str(interaction.guild.id)
        guild_settings = settings.get(sid, {})
        guild_settings['freewill_rate'] = rate
        settings[sid] = guild_settings
        save_settings(settings)
        await interaction.response.send_message(f"Natural replies rate set to **{rate}**.")

    @config_group.command(name="welcome", description="Toggle welcome messages in this channel")
    async def freewill_rate(interaction: Interaction):
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You must be a server administrator to use this command.", ephemeral=True)
            return
        permissions = interaction.channel.permissions_for(interaction.guild.me)
        if not permissions.send_messages:
            await interaction.response.send_message("I do not have permission to send messages in this channel.", ephemeral=True)
            return
        from bot import load_settings, save_settings
        settings = load_settings()
        sid = str(interaction.guild.id)
        guild_settings = settings.get(sid, {})
        allowed = guild_settings.get("welcome_msg", None)
        chan_id = interaction.channel_id
        if allowed == chan_id:
            guild_settings["welcome_msg"] = None
            action = "no longer"
        else:
            guild_settings["welcome_msg"] = chan_id
            action = "now"
        settings[sid] = guild_settings
        save_settings(settings)
        await interaction.response.send_message(
            f"{NAME} will {action} welcome new members in <#{chan_id}>.",
            ephemeral=False
        )

    @config_group.command(name="chatrevive-set", description=f"Make {NAME} send a chat revive message when the channel is inactive")
    @app_commands.describe(timeout="Time since last message in minutes before revive message is sent", role="Role to mention for chat revive")
    async def chatrevive(interaction: Interaction, timeout: app_commands.Range[int, 30, None], role: discord.Role):
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You must be a server administrator to use this command.", ephemeral=True)
            return
        permissions = interaction.channel.permissions_for(interaction.guild.me)
        if not permissions.send_messages:
            await interaction.response.send_message("I do not have permission to send messages in this channel.", ephemeral=True)
            return
        
        can_mention = False
        bot_member = interaction.guild.me
        if (permissions.mention_everyone and bot_member.top_role > role) or role.mentionable:
            can_mention = True
        if not can_mention:
            await interaction.response.send_message(
                f"I do not have permission to mention the role {role.mention} in this channel.",
                ephemeral=True
            )
            return

        from bot import load_settings, save_settings
        settings = load_settings()
        sid = str(interaction.guild.id)
        guild_settings = settings.get(sid, {})
        chatrevive = guild_settings.get("chatrevive", {})
        chan_id = interaction.channel_id
        if role is None:
            await interaction.response.send_message("You must specify a role to mention for chat revive.", ephemeral=True)
            return
        guild_settings["chatrevive"] = {
            "channel_id": chan_id,
            "timeout": timeout,
            "role_id": role.id
        }
        settings[sid] = guild_settings
        save_settings(settings)
        await interaction.response.send_message(
            f"Chat revive enabled for <#{chan_id}>. Timeout: {timeout} minutes. Role to mention: {role.mention}",
            ephemeral=False
        )

    @config_group.command(name="chatrevive-disable", description="Disable chat revive messages in this server.")
    async def chatrevive(interaction: Interaction):
        if not interaction.guild:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("You must be a server administrator to use this command.", ephemeral=True)
            return
        from bot import load_settings, save_settings
        settings = load_settings()
        sid = str(interaction.guild.id)
        guild_settings = settings.get(sid, {})
        chatrevive = guild_settings.get("chatrevive", {})
        chan_id = interaction.channel_id
        setting_chan_id = chatrevive.get("channel_id")
        if chatrevive.get("channel_id"):
            guild_settings["chatrevive"] = {}
            settings[sid] = guild_settings
            save_settings(settings)
            await interaction.response.send_message(f"Chat revive is now disabled for <#{setting_chan_id}>.", ephemeral=False)
        else:
            await interaction.response.send_message(f"Chat revive is already disabled in this server.", ephemeral=False)

    bot.tree.add_command(config_group)

    @bot.tree.command(name="delete-memories", description="Delete your memories")
    async def delete_memories(interaction: Interaction):
        class MyView(discord.ui.View):
            @discord.ui.button(label="Confirm", style=discord.ButtonStyle.primary, custom_id="confirm_delete")
            async def confirm_delete(self, interaction: Interaction, button: discord.ui.Button):
                user_id = interaction.user.id
                delete_user_memories(user_id)
                await interaction.response.send_message("Your memories have been deleted.", ephemeral=True)
        view = MyView()
        await interaction.response.send_message(
            "Are you sure you want to delete all memories related to you?\nIf yes, press the Confirm button.",
            view=view,
            ephemeral=True
        )

    @bot.tree.command(name="status", description="Show system status")
    async def status(interaction: Interaction):
        await interaction.response.defer(thinking=True)
        proc = psutil.Process(os.getpid())
        proc.cpu_percent(interval=None)
        latency_ms = round(interaction.client.latency * 1000, 2)
        bot_ram_usage = proc.memory_info().rss / (1024 * 1024)
        try:
            metrics_data = storage.load_user_metrics() or {}
            user_count = len(metrics_data)
        except Exception:
            user_count = 0
        bot_cpu_usage = proc.cpu_percent(interval=0)
        message = (
            f"### 🟢 {NAME} is online\n"
            f"> Latency: {latency_ms} ms\n"
            f"> CPU Usage: {bot_cpu_usage}%\n"
            f"> RAM Usage: {bot_ram_usage:.2f} MB\n"
            f"> Server count: {len(bot.guilds)}\n"
            f"> User count: {user_count}\n"
            f"-# Powered by WaterBot"
        )
        await interaction.followup.send(message)

    admin_group = app_commands.Group(name="admin", description="Admin commands")

    @admin_group.command(name="stats", description="Show detailed bot statistics with graphs")
    async def stats(interaction: Interaction):
        if interaction.user.id != OWNER_ID:
            return await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
        await interaction.response.defer(thinking=True, ephemeral=True)
        
        # System metrics
        proc = psutil.Process(os.getpid())
        bot_cpu_usage = proc.cpu_percent(interval=5)
        latency_ms = round(interaction.client.latency * 1000, 2)
        bot_ram_usage = proc.memory_info().rss / (1024 * 1024)
        try:
            uptime_seconds = time.time() - proc.create_time()
        except Exception:
            uptime_seconds = 0

        server_count = len(bot.guilds)
        try:
            metrics_data = storage.load_user_metrics() or {}
            user_count_from_file = len(metrics_data)
        except Exception:
            user_count_from_file = 0

        # Record metrics for history tracking
        try:
            messages_sent = int(metrics.messages_sent._value.get())
        except Exception:
            messages_sent = "N/A"
        
        try:
            metrics.record_daily_metrics(
                servers=server_count,
                users=user_count_from_file,
                messages=int(messages_sent) if isinstance(messages_sent, int) else 0
            )
        except Exception as e:
            if DEBUG:
                print(f"Error recording metrics: {e}")

        # Get storage data
        daily_messages = storage.load_daily_counts() or {}
        recent_freewill = storage.get_freewill_attempts() or {}
        recent_questions = storage.load_recent_questions() or {}
        serversettings = storage.load_settings() or {}
        daily_quiz = storage.load_daily_quiz_records() or {}
        user_metrics = storage.load_user_metrics() or {}

        try:
            daily_avg_active = "N/A"
            if isinstance(daily_messages, dict):
                date_keys = [k for k in daily_messages.keys() if not str(k).startswith('_')]
                if date_keys:
                    latest_date = sorted(date_keys)[-1]
                    latest_data = daily_messages.get(latest_date) or {}
                    counts = []
                    for v in latest_data.values():
                        try:
                            c = int(v)
                        except Exception:
                            continue
                        if c > 0:
                            counts.append(c)
                    if counts:
                        daily_avg_active = f"{(sum(counts) / len(counts)):.2f}"
                    else:
                        daily_avg_active = "0.00"
        except Exception:
            daily_avg_active = "N/A"

        try:
            avg_total_messages = "N/A"
            if isinstance(user_metrics, dict) and user_metrics:
                totals = []
                for val in user_metrics.values():
                    if isinstance(val, dict):
                        m = val.get('messages') or val.get('message') or 0
                        try:
                            totals.append(int(m))
                        except Exception:
                            continue
                    else:
                        try:
                            totals.append(int(val))
                        except Exception:
                            continue
                if totals:
                    avg_total_messages = f"{(sum(totals) / len(totals)):.2f}"
                else:
                    avg_total_messages = "0.00"
        except Exception:
            avg_total_messages = "N/A"

        try:
            from memory import get_all_summaries, _read_json_encrypted
            all_summaries = get_all_summaries() or []
            memory_count = len(all_summaries)
            try:
                user_mem_data = _read_json_encrypted('user_memories_enc') or {}
                user_mem_count = len(user_mem_data.keys()) if isinstance(user_mem_data, dict) else 0
            except Exception:
                user_mem_count = "N/A"
        except Exception:
            memory_count = "N/A"
            user_mem_count = "N/A"

        # Get growth stats
        growth_stats = metrics.get_growth_stats()

        # Create embeds
        embeds = []
        
        # System Status Embed
        system_embed = discord.Embed(
            title="🖥️ System Status",
            color=discord.Color.blue(),
            description="Current bot performance and resource usage"
        )
        system_embed.add_field(name="Latency", value=f"{latency_ms} ms", inline=True)
        system_embed.add_field(name="CPU Usage", value=f"{bot_cpu_usage}%", inline=True)
        system_embed.add_field(name="RAM Usage", value=f"{bot_ram_usage:.2f} MB", inline=True)
        system_embed.add_field(name="Uptime", value=f"{int(uptime_seconds)} seconds ({int(uptime_seconds // 3600)}h {int((uptime_seconds % 3600) // 60)}m)", inline=True)
        embeds.append(system_embed)

        # Server & User Growth Embed
        growth_embed = discord.Embed(
            title="📊 Growth Metrics",
            color=discord.Color.green(),
            description="Current and historical growth data"
        )
        growth_embed.add_field(name="Current Servers", value=f"**{server_count}**", inline=True)
        growth_embed.add_field(name="Current Users", value=f"**{user_count_from_file}**", inline=True)
        growth_embed.add_field(name="Messages Tracked", value=f"**{messages_sent}**", inline=True)
        
        if growth_stats.get("available"):
            weekly_servers = growth_stats.get("weekly", {}).get("servers", 0)
            weekly_servers_pct = growth_stats.get("weekly", {}).get("servers_pct", 0)
            weekly_users = growth_stats.get("weekly", {}).get("users", 0)
            weekly_users_pct = growth_stats.get("weekly", {}).get("users_pct", 0)
            
            server_emoji = "📈" if weekly_servers >= 0 else "📉"
            user_emoji = "📈" if weekly_users >= 0 else "📉"
            
            growth_embed.add_field(
                name="Weekly Growth",
                value=f"{server_emoji} Servers: {weekly_servers:+d} ({weekly_servers_pct:+.1f}%)\n{user_emoji} Users: {weekly_users:+d} ({weekly_users_pct:+.1f}%)",
                inline=False
            )
            
            monthly_servers = growth_stats.get("monthly", {}).get("servers", 0)
            monthly_servers_pct = growth_stats.get("monthly", {}).get("servers_pct", 0)
            monthly_users = growth_stats.get("monthly", {}).get("users", 0)
            monthly_users_pct = growth_stats.get("monthly", {}).get("users_pct", 0)
            
            server_emoji = "📈" if monthly_servers >= 0 else "📉"
            user_emoji = "📈" if monthly_users >= 0 else "📉"
            
            growth_embed.add_field(
                name="Monthly Growth",
                value=f"{server_emoji} Servers: {monthly_servers:+d} ({monthly_servers_pct:+.1f}%)\n{user_emoji} Users: {monthly_users:+d} ({monthly_users_pct:+.1f}%)",
                inline=False
            )
        
        embeds.append(growth_embed)

        # Engagement Embed
        engagement_embed = discord.Embed(
            title="💬 Engagement",
            color=discord.Color.gold(),
            description="Message and activity statistics"
        )
        engagement_embed.add_field(name="Avg Daily Messages (Latest)", value=daily_avg_active, inline=True)
        engagement_embed.add_field(name="Avg Messages per User", value=avg_total_messages, inline=True)
        engagement_embed.add_field(name="Daily Message Records", value=len(daily_messages), inline=True)
        embeds.append(engagement_embed)

        # Data Storage Embed
        storage_embed = discord.Embed(
            title="💾 Data Storage",
            color=discord.Color.greyple(),
            description="Information about stored data"
        )
        storage_embed.add_field(name="Memory Summaries", value=memory_count, inline=True)
        storage_embed.add_field(name="Users with Memories", value=user_mem_count, inline=True)
        storage_embed.add_field(name="Quiz Records", value=len(daily_quiz), inline=True)
        storage_embed.add_field(name="Server Settings", value=len(serversettings), inline=True)
        storage_embed.add_field(name="User Metrics", value=len(user_metrics), inline=True)
        storage_embed.add_field(name="Natural Replies Entries", value=len(recent_freewill), inline=True)
        storage_embed.add_field(name="Recent Questions", value=len(recent_questions), inline=True)
        embeds.append(storage_embed)

        # Send embeds
        await interaction.followup.send(embeds=embeds, ephemeral=True)

        # Try to generate and send graphs
        try:
            combined_graph = metrics.generate_combined_graph(days=30)
            if combined_graph:
                await interaction.followup.send(file=discord.File(combined_graph, filename="growth_30d.png"), ephemeral=True)
        except Exception as e:
            if DEBUG:
                print(f"Error generating combined graph: {e}")

    @admin_group.command(name="stats-graphs", description="Show detailed statistical graphs")
    @app_commands.describe(days="Number of days to show (7, 14, 30, 60, 90)", metric="Which metric to graph")
    @app_commands.choices(days=[
        app_commands.Choice(name="Last 7 Days", value="7"),
        app_commands.Choice(name="Last 14 Days", value="14"),
        app_commands.Choice(name="Last 30 Days", value="30"),
        app_commands.Choice(name="Last 60 Days", value="60"),
        app_commands.Choice(name="Last 90 Days", value="90"),
    ], metric=[
        app_commands.Choice(name="Servers", value="servers"),
        app_commands.Choice(name="Users", value="users"),
        app_commands.Choice(name="Messages", value="messages"),
        app_commands.Choice(name="All Growth Metrics", value="combined"),
    ])
    async def stats_graphs(interaction: Interaction, days: str = "30", metric: str = "combined"):
        if interaction.user.id != OWNER_ID:
            return await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
        
        await interaction.response.defer(thinking=True, ephemeral=True)
        
        days_int = int(days)
        
        try:
            if metric == "combined":
                graph_buffer = metrics.generate_combined_graph(days=days_int)
                if graph_buffer:
                    await interaction.followup.send(
                        file=discord.File(graph_buffer, filename=f"growth_{days_int}d.png"),
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send("Could not generate graph. Make sure matplotlib is installed.", ephemeral=True)
            else:
                graph_buffer = metrics.generate_graph(metric_type=metric, days=days_int)
                if graph_buffer:
                    metric_name = metric.replace('_', ' ').title()
                    await interaction.followup.send(
                        file=discord.File(graph_buffer, filename=f"{metric}_{days_int}d.png"),
                        ephemeral=True
                    )
                else:
                    await interaction.followup.send("Could not generate graph. Ensure there is historical data available.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"Error generating graph: {str(e)}", ephemeral=True)
            if DEBUG:
                print(f"Graph generation error: {e}")

    @admin_group.command(name="ban", description="Ban or unban a user")
    @app_commands.describe(action="Choose ban or unban", user="The user to affect")
    @app_commands.choices(action=[
        app_commands.Choice(name="Ban", value="ban"),
        app_commands.Choice(name="Unban", value="unban")
    ])
    async def ban_toggle(interaction: Interaction, action: str, user: discord.User):
        if interaction.user.id != OWNER_ID:
            return await interaction.response.send_message("You are not authorized to use this command.", ephemeral=True)
        
        try:
            banned_map = storage.load_banned_map() or {}
        except Exception:
            banned_map = {}

        uid = int(user.id)
        if action == 'ban':
            if uid in banned_map:
                return await interaction.response.send_message(f"{user} is already banned.", ephemeral=True)
            banned_map[uid] = {'notified': False}
            try:
                storage.save_banned_map(banned_map)
            except Exception:
                return await interaction.response.send_message("Failed to save banned users list.", ephemeral=True)
            await interaction.response.send_message(f"Banned {user} from using the bot.", ephemeral=True)
        else:
            if uid not in banned_map:
                return await interaction.response.send_message(f"{user} is not banned.", ephemeral=True)
            try:
                banned_map.pop(uid, None)
                storage.save_banned_map(banned_map)
            except Exception:
                return await interaction.response.send_message("Failed to update banned users list.", ephemeral=True)
            await interaction.response.send_message(f"Unbanned {user}.", ephemeral=True)


    bot.tree.add_command(admin_group)