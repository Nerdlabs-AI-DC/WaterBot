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

import threading
import time
import datetime
import io
from typing import Dict, Optional
from pathlib import Path
import json
import storage

_LOCK = threading.Lock()


def update_metrics(user_id: int) -> None:
	key = str(user_id)
	metrics = storage.load_user_metrics() or {}
	if not isinstance(metrics, dict):
		metrics = {}

	current = metrics.get(key)
	if isinstance(current, dict):
		current['messages'] = int(current.get('messages') or 0) + 1
		metrics[key] = current
	elif isinstance(current, int):
		metrics[key] = current + 1
	else:
		metrics[key] = 1

	try:
		storage.save_user_metrics(metrics)
		_update_bot_meta_with_user_count()
	except Exception:
		return


def _load():
	try:
		return storage.load_metrics() or {"messages_sent": 0, "updated_at": time.time()}
	except Exception:
		return {"messages_sent": 0, "updated_at": time.time()}


def _save(data: dict):
	data["updated_at"] = time.time()
	storage.save_metrics(data)


def _get_unique_user_count() -> int:
	"""Get the count of unique users who have interacted with the bot"""
	try:
		metrics = storage.load_user_metrics() or {}
		return len(metrics)
	except Exception:
		return 0


def _update_bot_meta_with_user_count() -> None:
	"""Update bot_meta.json with the current unique user count"""
	try:
		shared_dir = Path("shared")
		bot_meta_path = shared_dir / "bot_meta.json"
		
		shared_dir.mkdir(parents=True, exist_ok=True)
		
		bot_meta = {}
		if bot_meta_path.exists():
			try:
				with open(bot_meta_path, 'r') as f:
					bot_meta = json.load(f)
			except Exception:
				bot_meta = {}

		bot_meta["unique_users"] = _get_unique_user_count()
		
		with open(bot_meta_path, 'w') as f:
			json.dump(bot_meta, f, indent=2)
	except Exception as e:
		print(f"Error updating bot_meta.json: {e}")


class _ValueHolder:
	def __init__(self, getter):
		self._getter = getter

	def get(self):
		try:
			return int(self._getter())
		except Exception:
			return 0


class Counter:
	def __init__(self, key: str):
		self.key = key
		self._value = _ValueHolder(lambda: _load().get(self.key, 0))

	def inc(self, amount: int = 1):
		with _LOCK:
			data = _load()
			data[self.key] = int(data.get(self.key, 0)) + int(amount)
			_save(data)


messages_sent = Counter('messages_sent')


# ==================== HISTORICAL METRICS ====================
# Keys for storing metrics history
METRICS_HISTORY_KEY = "metrics_history"
DAILY_METRICS_KEY = "daily_metrics"


def record_metrics(servers: int, users: int, messages: int, cpu: float, ram: float) -> None:
	try:
		history = storage.get_json(METRICS_HISTORY_KEY, {})
		if not isinstance(history, dict):
			history = {}
		
		timestamp = datetime.datetime.utcnow().isoformat()
		history[timestamp] = {
			"servers": servers,
			"users": users,
			"messages": messages,
			"cpu": cpu,
			"ram": ram,
		}
		
		timestamps = sorted(history.keys())
		if len(timestamps) > 129600:
			for ts in timestamps[:-129600]:
				del history[ts]
		
		storage.set_json(METRICS_HISTORY_KEY, history)
	except Exception as e:
		print(f"Error recording metrics: {e}")


def record_daily_metrics(day: Optional[str] = None, servers: Optional[int] = None, 
						users: Optional[int] = None, messages: Optional[int] = None) -> None:
	try:
		if day is None:
			day = datetime.datetime.utcnow().date().isoformat()
		
		daily = storage.get_json(DAILY_METRICS_KEY, {})
		if not isinstance(daily, dict):
			daily = {}
		
		if day not in daily:
			daily[day] = {}
		
		day_data = daily[day]
		if servers is not None:
			day_data["servers"] = servers
		if users is not None:
			day_data["users"] = users
		if messages is not None:
			day_data["messages"] = messages
		
		daily[day] = day_data
		storage.set_json(DAILY_METRICS_KEY, daily)
		
		# Update bot_meta.json with current metrics
		_update_bot_meta_with_user_count()
	except Exception as e:
		print(f"Error recording daily metrics: {e}")


def get_metrics_history(days: int = 30, metric_type: str = "servers") -> Dict[str, int]:
	try:
		daily = storage.get_json(DAILY_METRICS_KEY, {})
		if not isinstance(daily, dict):
			return {}
		
		result = {}
		cutoff_date = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).date()
		
		for date_str in sorted(daily.keys()):
			try:
				date_obj = datetime.datetime.fromisoformat(date_str).date()
				if date_obj >= cutoff_date:
					value = daily[date_str].get(metric_type)
					if value is not None:
						result[date_str] = value
			except Exception:
				continue
		
		return result
	except Exception as e:
		print(f"Error retrieving metrics history: {e}")
		return {}


def get_growth_stats() -> Dict:
	try:
		daily = storage.get_json(DAILY_METRICS_KEY, {})
		if not isinstance(daily, dict) or len(daily) < 2:
			return {"available": False}
		
		sorted_dates = sorted(daily.keys())
		today = sorted_dates[-1] if sorted_dates else None
		
		if not today:
			return {"available": False}
		
		today_data = daily.get(today, {})
		today_servers = today_data.get("servers", 0)
		today_users = today_data.get("users", 0)
		
		stats = {
			"available": True,
			"today_servers": today_servers,
			"today_users": today_users,
			"weekly": {},
			"monthly": {},
		}
		
		# Weekly comparison
		week_ago_idx = max(0, len(sorted_dates) - 8)
		week_ago_date = sorted_dates[week_ago_idx]
		week_ago_data = daily.get(week_ago_date, {})
		week_ago_servers = week_ago_data.get("servers", 0)
		week_ago_users = week_ago_data.get("users", 0)
		
		if week_ago_servers > 0:
			stats["weekly"]["servers"] = today_servers - week_ago_servers
			stats["weekly"]["servers_pct"] = ((today_servers - week_ago_servers) / week_ago_servers * 100) if week_ago_servers > 0 else 0
		if week_ago_users > 0:
			stats["weekly"]["users"] = today_users - week_ago_users
			stats["weekly"]["users_pct"] = ((today_users - week_ago_users) / week_ago_users * 100) if week_ago_users > 0 else 0
		
		# Monthly comparison
		month_ago_idx = max(0, len(sorted_dates) - 31)
		month_ago_date = sorted_dates[month_ago_idx]
		month_ago_data = daily.get(month_ago_date, {})
		month_ago_servers = month_ago_data.get("servers", 0)
		month_ago_users = month_ago_data.get("users", 0)
		
		if month_ago_servers > 0:
			stats["monthly"]["servers"] = today_servers - month_ago_servers
			stats["monthly"]["servers_pct"] = ((today_servers - month_ago_servers) / month_ago_servers * 100) if month_ago_servers > 0 else 0
		if month_ago_users > 0:
			stats["monthly"]["users"] = today_users - month_ago_users
			stats["monthly"]["users_pct"] = ((today_users - month_ago_users) / month_ago_users * 100) if month_ago_users > 0 else 0
		
		return stats
	except Exception as e:
		print(f"Error calculating growth stats: {e}")
		return {"available": False}


def generate_graph(metric_type: str = "servers", days: int = 30, title: str = None) -> Optional[io.BytesIO]:
	try:
		import matplotlib
		matplotlib.use('Agg')
		import matplotlib.pyplot as plt
		
		history = get_metrics_history(days=days, metric_type=metric_type)
		
		if not history:
			return None
		
		dates = list(history.keys())
		values = list(history.values())
		
		# Create figure with better styling
		fig, ax = plt.subplots(figsize=(12, 6), dpi=100)
		fig.patch.set_facecolor('#36393f')
		ax.set_facecolor('#2f3136')
		
		# Plot data
		ax.plot(dates, values, color='#7289da', linewidth=2.5, marker='o', markersize=4)
		ax.fill_between(range(len(dates)), values, alpha=0.3, color='#7289da')
		
		# Styling
		ax.set_title(title or f"{metric_type.replace('_', ' ').title()} - Last {days} Days", 
					fontsize=14, color='#dcddde', fontweight='bold', pad=20)
		ax.set_xlabel('Date', fontsize=11, color='#dcddde')
		ax.set_ylabel(metric_type.replace('_', ' ').title(), fontsize=11, color='#dcddde')
		
		# Grid
		ax.grid(True, alpha=0.2, color='#72767d')
		
		# Tick styling
		ax.tick_params(colors='#dcddde', labelsize=9)
		for spine in ax.spines.values():
			spine.set_color('#72767d')
		
		# Rotate x-axis labels for readability
		plt.xticks(rotation=45, ha='right')
		
		# Tight layout
		plt.tight_layout()
		
		# Save to BytesIO
		img_buffer = io.BytesIO()
		fig.savefig(img_buffer, format='png', facecolor=fig.get_facecolor(), edgecolor='none')
		img_buffer.seek(0)
		plt.close(fig)
		
		return img_buffer
	except ImportError:
		print("matplotlib not installed for graph generation")
		return None
	except Exception as e:
		print(f"Error generating graph: {e}")
		return None


def generate_combined_graph(days: int = 30) -> Optional[io.BytesIO]:
	try:
		import matplotlib
		matplotlib.use('Agg')
		import matplotlib.pyplot as plt
		
		servers_history = get_metrics_history(days=days, metric_type="servers")
		users_history = get_metrics_history(days=days, metric_type="users")
		
		if not servers_history or not users_history:
			return None
		
		dates = list(servers_history.keys())
		servers = list(servers_history.values())
		users = list(users_history.values())
		
		# Create figure with better styling
		fig, ax1 = plt.subplots(figsize=(12, 6), dpi=100)
		fig.patch.set_facecolor('#36393f')
		ax1.set_facecolor('#2f3136')
		
		# First axis - Servers
		color1 = '#7289da'
		ax1.set_xlabel('Date', fontsize=11, color='#dcddde')
		ax1.set_ylabel('Servers', fontsize=11, color=color1)
		ax1.plot(dates, servers, color=color1, linewidth=2.5, marker='o', markersize=4, label='Servers')
		ax1.tick_params(axis='y', labelcolor=color1)
		ax1.tick_params(axis='x', colors='#dcddde', labelsize=9)
		
		# Second axis - Users
		ax2 = ax1.twinx()
		ax2.set_facecolor('#2f3136')
		color2 = '#43b581'
		ax2.set_ylabel('Users', fontsize=11, color=color2)
		ax2.plot(dates, users, color=color2, linewidth=2.5, marker='s', markersize=4, label='Users')
		ax2.tick_params(axis='y', labelcolor=color2)
		
		# Title and styling
		fig.suptitle('Growth Metrics - Last 30 Days', fontsize=14, color='#dcddde', fontweight='bold', y=0.98)
		
		# Grid
		ax1.grid(True, alpha=0.2, color='#72767d')
		
		# Spines
		for spine in ax1.spines.values():
			spine.set_color('#72767d')
		for spine in ax2.spines.values():
			spine.set_color('#72767d')
		
		# Rotate x-axis labels
		plt.xticks(rotation=45, ha='right')
		
		# Legend
		lines1, labels1 = ax1.get_legend_handles_labels()
		lines2, labels2 = ax2.get_legend_handles_labels()
		ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', framealpha=0.9, facecolor='#2f3136', edgecolor='#72767d', labelcolor='#dcddde')
		
		plt.tight_layout()
		
		# Save to BytesIO
		img_buffer = io.BytesIO()
		fig.savefig(img_buffer, format='png', facecolor=fig.get_facecolor(), edgecolor='none')
		img_buffer.seek(0)
		plt.close(fig)
		
		return img_buffer
	except ImportError:
		print("matplotlib not installed for graph generation")
		return None
	except Exception as e:
		print(f"Error generating combined graph: {e}")
		return None