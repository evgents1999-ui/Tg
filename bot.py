import logging
import asyncio
from enum import Enum
from datetime import datetime, timedelta
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Choice(Enum):
    ROCK = "🪨 Камень"
    SCISSORS = "✂️ Ножницы"
    PAPER = "📄 Бумага"

class AdminRank(Enum):
    OWNER = 4      # Владелец - полный доступ
    SUPER_ADMIN = 3  # Супер-админ - почти полный доступ
    ADMIN = 2       # Админ - базовые права
    HELPER = 1      # Помощник - ограниченные права

class Game:
    def __init__(self, game_id: int, player1: int):
        self.id = game_id
        self.player1 = player1
        self.player2 = None
        self.choice1 = None
        self.choice2 = None
        self.created_time = datetime.now()
        self.last_action_time = datetime.now()
    
    def add_player(self, player_id: int):
        if not self.player2 and player_id != self.player1:
            self.player2 = player_id
            self.last_action_time = datetime.now()
            return True
        return False
    
    def make_choice(self, player_id: int, choice: Choice):
        if player_id == self.player1:
            self.choice1 = choice
        elif player_id == self.player2:
            self.choice2 = choice
        self.last_action_time = datetime.now()
    
    def is_ready(self):
        return self.choice1 and self.choice2
    
    def is_expired(self, seconds=30):
        return (datetime.now() - self.last_action_time).total_seconds() > seconds
    
    def get_winner(self):
        if not self.is_ready() or self.choice1 == self.choice2:
            return None
        
        wins = {
            Choice.ROCK: Choice.SCISSORS,
            Choice.SCISSORS: Choice.PAPER, 
            Choice.PAPER: Choice.ROCK
        }
        
        if wins[self.choice1] == self.choice2:
            return self.player1
        return self.player2

class GameBot:
    def __init__(self):
        self.games = {}
        self.players_in_queue = []
        self.game_counter = 0
        # 🔧 СИСТЕМА АДМИНОВ: {user_id: AdminRank}
        self.admins = {
            7296765144: AdminRank.OWNER,  # Главный админ (владелец)
            # Примеры других админов (раскомментируйте и замените ID):
            # 123456789: AdminRank.SUPER_ADMIN,
            # 987654321: AdminRank.ADMIN,
            # 555555555: AdminRank.HELPER,
        }
        self.user_stats = {}  # {user_id: {"wins": 0, "losses": 0, "draws": 0, "win_streak": 0, "max_win_streak": 0}}
        self.banned_users = {}  # {user_id: {"reason": str, "banned_by": int, "banned_at": datetime}}
    
    def is_admin(self, user_id: int) -> bool:
        """Проверяет, является ли пользователь админом"""
        return user_id in self.admins
    
    def is_banned(self, user_id: int) -> bool:
        """Проверяет, забанен ли пользователь"""
        return user_id in self.banned_users
    
    def get_admin_rank(self, user_id: int) -> AdminRank:
        """Возвращает ранг админа"""
        return self.admins.get(user_id)
    
    def has_permission(self, user_id: int, required_rank: AdminRank) -> bool:
        """Проверяет, есть ли у админа достаточный ранг"""
        if not self.is_admin(user_id):
            return False
        return self.admins[user_id].value >= required_rank.value
    
    def get_rank_name(self, rank: AdminRank) -> str:
        """Возвращает название ранга"""
        names = {
            AdminRank.OWNER: "👑 Владелец",
            AdminRank.SUPER_ADMIN: "⚡ Супер-Админ", 
            AdminRank.ADMIN: "🔧 Админ",
            AdminRank.HELPER: "🛠️ Помощник"
        }
        return names.get(rank, "❓ Неизвестно")
    
    async def ban_user(self, update, context):
        """Забанить пользователя"""
        user_id = update.effective_user.id
        
        if not self.has_permission(user_id, AdminRank.SUPER_ADMIN):
            await update.message.reply_text("❌ Недостаточно прав. Нужен ранг Супер-Админ или выше.")
            return
        
        if not context.args or len(context.args) < 2:
            await update.message.reply_text(
                "🔨 Бан пользователя\n\n"
                "Использование:\n"
                "/ban [ID] [причина]\n\n"
                "Пример:\n"
                "/ban 123456789 нарушение правил\n\n"
                f"📊 Забанено пользователей: {len(self.banned_users)}"
            )
            return
        
        try:
            target_id = int(context.args[0])
            reason = " ".join(context.args[1:])
            
            if target_id in self.admins:
                await update.message.reply_text("❌ Нельзя забанить админа")
                return
            
            if self.is_banned(target_id):
                await update.message.reply_text("❌ Этот пользователь уже забанен")
                return
            
            # Баним пользователя
            self.banned_users[target_id] = {
                "reason": reason,
                "banned_by": user_id,
                "banned_at": datetime.now()
            }
            
            # Удаляем пользователя из активных игр
            for game_id, game in list(self.games.items()):
                if target_id in [game.player1, game.player2]:
                    opponent = game.player1 if target_id == game.player2 else game.player2
                    del self.games[game_id]
                    if opponent:
                        try:
                            await context.bot.send_message(opponent, "❌ Игра отменена - противник забанен")
                        except:
                            pass
            
            await update.message.reply_text(
                f"🔨 Пользователь {target_id} забанен!\n\n"
                f"📝 Причина: {reason}\n"
                f"👮 Забанил: {user_id}\n\n"
                f"📊 Всего забанено: {len(self.banned_users)}"
            )
            
        except ValueError:
            await update.message.reply_text("❌ Неверный формат ID. Используйте числа.")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    async def unban_user(self, update, context):
        """Разбанить пользователя"""
        user_id = update.effective_user.id
        
        if not self.has_permission(user_id, AdminRank.SUPER_ADMIN):
            await update.message.reply_text("❌ Недостаточно прав. Нужен ранг Супер-Админ или выше.")
            return
        
        if not context.args:
            await update.message.reply_text(
                "🔓 Разбан пользователя\n\n"
                "Использование:\n"
                "/unban [ID]\n\n"
                "Пример:\n"
                "/unban 123456789\n\n"
                f"📊 Забанено пользователей: {len(self.banned_users)}"
            )
            return
        
        try:
            target_id = int(context.args[0])
            
            if not self.is_banned(target_id):
                await update.message.reply_text("❌ Этот пользователь не забанен")
                return
            
            # Разбаниваем пользователя
            ban_info = self.banned_users.pop(target_id)
            
            await update.message.reply_text(
                f"🔓 Пользователь {target_id} разбанен!\n\n"
                f"📝 Была причина: {ban_info['reason']}\n"
                f"👮 Забанил: {ban_info['banned_by']}\n"
                f"⏰ Бан длился: {(datetime.now() - ban_info['banned_at']).total_seconds() / 60:.1f} мин.\n\n"
                f"📊 Осталось забанено: {len(self.banned_users)}"
            )
            
        except ValueError:
            await update.message.reply_text("❌ Неверный формат ID. Используйте числа.")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    async def ban_list(self, update, context):
        """Показать список забаненных пользователей"""
        user_id = update.effective_user.id
        
        if not self.has_permission(user_id, AdminRank.SUPER_ADMIN):
            await update.message.reply_text("❌ Недостаточно прав. Нужен ранг Супер-Админ или выше.")
            return
        
        if not self.banned_users:
            await update.message.reply_text("📋 Список банов пуст")
            return
        
        ban_list = "🔨 Список забаненных пользователей:\n\n"
        for banned_id, ban_info in self.banned_users.items():
            ban_duration = (datetime.now() - ban_info['banned_at']).total_seconds() / 60
            ban_list += f"👤 {banned_id}\n📝 {ban_info['reason']}\n⏰ {ban_duration:.1f} мин. назад\n👮 {ban_info['banned_by']}\n\n"
        
        await update.message.reply_text(ban_list)
    
    def update_stats(self, user_id, result):
        """Обновляем статистику пользователя с винстриком"""
        if user_id not in self.user_stats:
            self.user_stats[user_id] = {
                "wins": 0, 
                "losses": 0, 
                "draws": 0, 
                "win_streak": 0, 
                "max_win_streak": 0
            }
        
        stats = self.user_stats[user_id]
        
        if result == "win":
            stats["wins"] += 1
            stats["win_streak"] += 1
            # Обновляем максимальный винстрик
            if stats["win_streak"] > stats["max_win_streak"]:
                stats["max_win_streak"] = stats["win_streak"]
        elif result == "loss":
            stats["losses"] += 1
            stats["win_streak"] = 0  # Сбрасываем винстрик при поражении
        elif result == "draw":
            stats["draws"] += 1
            # Винстрик не сбрасывается при ничьей
    
    async def reset_all_stats(self, update, context):
        """УДАЛИТЬ ВСЕ СТАТИСТИКИ (только для владельца)"""
        user_id = update.effective_user.id
        
        if not self.has_permission(user_id, AdminRank.OWNER):
            await update.message.reply_text("❌ Эта команда только для владельца бота!")
            return
        
        # Запрос подтверждения
        if not context.args or context.args[0] != "confirm":
            await update.message.reply_text(
                "⚠️ ⚠️ ⚠️ ВНИМАНИЕ! ⚠️ ⚠️ ⚠️\n\n"
                "Эта команда УДАЛИТ ВСЮ СТАТИСТИКУ всех игроков!\n"
                "Это действие НЕОБРАТИМО!\n\n"
                "Для подтверждения введите:\n"
                "/reset_all_stats confirm\n\n"
                f"📊 Сейчас в статистике: {len(self.user_stats)} игроков"
            )
            return
        
        # Сохраняем старую статистику для отчета
        old_stats_count = len(self.user_stats)
        total_wins = sum(stats["wins"] for stats in self.user_stats.values())
        total_losses = sum(stats["losses"] for stats in self.user_stats.values())
        total_draws = sum(stats["draws"] for stats in self.user_stats.values())
        
        # Полностью очищаем статистику
        self.user_stats.clear()
        
        await update.message.reply_text(
            "🗑️ ВСЯ СТАТИСТИКА УДАЛЕНА!\n\n"
            f"📊 Было удалено:\n"
            f"• Игроков: {old_stats_count}\n"
            f"• Побед: {total_wins}\n"
            f"• Поражений: {total_losses}\n"
            f"• Ничьих: {total_draws}\n"
            f"• Всего игр: {total_wins + total_losses + total_draws}\n\n"
            "🔄 Статистика полностью обнулена!"
        )
    
    async def reset_player_stats(self, update, context):
        """Удалить статистику конкретного игрока"""
        user_id = update.effective_user.id
        
        if not self.has_permission(user_id, AdminRank.SUPER_ADMIN):
            await update.message.reply_text("❌ Недостаточно прав. Нужен ранг Супер-Админ или выше.")
            return
        
        if not context.args:
            await update.message.reply_text(
                "🎯 Удаление статистики игрока\n\n"
                "Использование:\n"
                "/reset_player_stats [ID_игрока]\n\n"
                "Пример:\n"
                "/reset_player_stats 123456789\n\n"
                "⚠️ Статистика будет полностью обнулена!"
            )
            return
        
        try:
            target_id = int(context.args[0])
            
            if target_id not in self.user_stats:
                await update.message.reply_text("❌ У этого игрока нет статистики")
                return
            
            # Сохраняем старую статистику для отчета
            old_stats = self.user_stats[target_id].copy()
            
            # Удаляем статистику игрока
            del self.user_stats[target_id]
            
            await update.message.reply_text(
                f"✅ Статистика игрока {target_id} удалена!\n\n"
                f"📊 Было удалено:\n"
                f"• Побед: {old_stats['wins']}\n"
                f"• Поражений: {old_stats['losses']}\n"
                f"• Ничьих: {old_stats['draws']}\n"
                f"• Винстрик: {old_stats['win_streak']}\n"
                f"• Макс. винстрик: {old_stats['max_win_streak']}\n"
                f"• Всего игр: {old_stats['wins'] + old_stats['losses'] + old_stats['draws']}"
            )
            
        except ValueError:
            await update.message.reply_text("❌ Неверный формат ID. Используйте числа.")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    async def add_admin(self, update, context):
        """Добавить нового админа"""
        user_id = update.effective_user.id
        
        if not self.has_permission(user_id, AdminRank.SUPER_ADMIN):
            await update.message.reply_text("❌ Недостаточно прав. Нужен ранг Супер-Админ или выше.")
            return
        
        if not context.args or len(context.args) < 2:
            await update.message.reply_text(
                "👥 Добавление админа\n\n"
                "Использование:\n"
                "/add_admin [ID] [ранг]\n\n"
                "Ранги:\n"
                "1 - 🛠️ Помощник\n"
                "2 - 🔧 Админ\n"
                "3 - ⚡ Супер-Админ\n\n"
                "Пример:\n"
                "/add_admin 123456789 2\n\n"
                f"Текущие админы: {len(self.admins)}"
            )
            return
        
        try:
            new_admin_id = int(context.args[0])
            rank_level = int(context.args[1])
            
            if new_admin_id in self.admins:
                await update.message.reply_text("❌ Этот пользователь уже админ")
                return
            
            # Проверяем валидность ранга
            if rank_level not in [1, 2, 3]:
                await update.message.reply_text("❌ Неверный ранг. Используйте: 1, 2 или 3")
                return
            
            # Нельзя назначать ранг выше своего
            user_rank = self.get_admin_rank(user_id)
            if rank_level > user_rank.value:
                await update.message.reply_text("❌ Нельзя назначить ранг выше своего")
                return
            
            new_rank = AdminRank(rank_level)
            self.admins[new_admin_id] = new_rank
            
            await update.message.reply_text(
                f"✅ Пользователь {new_admin_id} добавлен как {self.get_rank_name(new_rank)}!\n\n"
                f"📋 Теперь админов: {len(self.admins)}"
            )
            
        except ValueError:
            await update.message.reply_text("❌ Неверный формат. Используйте: /add_admin [ID] [ранг]")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    async def remove_admin(self, update, context):
        """Удалить админа"""
        user_id = update.effective_user.id
        
        if not self.has_permission(user_id, AdminRank.SUPER_ADMIN):
            await update.message.reply_text("❌ Недостаточно прав. Нужен ранг Супер-Админ или выше.")
            return
        
        if not context.args:
            await update.message.reply_text(
                "👥 Удаление админа\n\n"
                "Использование:\n"
                "/remove_admin [ID]\n\n"
                "Пример:\n"
                "/remove_admin 123456789\n\n"
                f"Текущие админы: {len(self.admins)}"
            )
            return
        
        try:
            remove_admin_id = int(context.args[0])
            
            if remove_admin_id not in self.admins:
                await update.message.reply_text("❌ Этот пользователь не админ")
                return
            
            # Нельзя удалить владельца
            if self.admins[remove_admin_id] == AdminRank.OWNER:
                await update.message.reply_text("❌ Нельзя удалить владельца бота!")
                return
            
            # Нельзя удалить админа равного или выше ранга
            user_rank = self.get_admin_rank(user_id)
            target_rank = self.get_admin_rank(remove_admin_id)
            
            if target_rank.value >= user_rank.value:
                await update.message.reply_text("❌ Нельзя удалить админа равного или выше ранга")
                return
            
            removed_rank = self.admins.pop(remove_admin_id)
            await update.message.reply_text(
                f"✅ {self.get_rank_name(removed_rank)} {remove_admin_id} удален!\n\n"
                f"📋 Осталось админов: {len(self.admins)}"
            )
            
        except ValueError:
            await update.message.reply_text("❌ Неверный формат ID. Используйте числа.")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    async def list_admins(self, update, context):
        """Показать список админов"""
        user_id = update.effective_user.id
        
        if not self.is_admin(user_id):
            await update.message.reply_text("❌ Доступ запрещен")
            return
        
        if not self.admins:
            await update.message.reply_text("📋 Список админов пуст")
            return
        
        admin_list = "👥 Список админов:\n\n"
        for admin_id, rank in sorted(self.admins.items(), key=lambda x: x[1].value, reverse=True):
            admin_list += f"{self.get_rank_name(rank)} - {admin_id}\n"
        
        await update.message.reply_text(admin_list)
    
    async def my_rank(self, update, context):
        """Показать свой ранг"""
        user_id = update.effective_user.id
        
        if not self.is_admin(user_id):
            await update.message.reply_text("❌ Вы не админ")
            return
        
        rank = self.get_admin_rank(user_id)
        permissions = self.get_admin_permissions(rank)
        
        text = f"🎖️ Ваш ранг: {self.get_rank_name(rank)}\n\n"
        text += "📋 Ваши права:\n" + "\n".join([f"• {perm}" for perm in permissions])
        
        await update.message.reply_text(text)
    
    def get_admin_permissions(self, rank: AdminRank) -> list:
        """Возвращает список прав для ранга"""
        permissions = {
            AdminRank.OWNER: [
                "Все права", "Управление всеми админами", "Накрутка побед",
                "Очистка игр", "Просмотр статистики", "Удаление любых админов",
                "УДАЛЕНИЕ ВСЕЙ СТАТИСТИКИ", "Бан пользователей"
            ],
            AdminRank.SUPER_ADMIN: [
                "Управление админами (кроме владельца)", "Накрутка побед",
                "Очистка игр", "Просмотр статистики", "Удаление младших админов",
                "Удаление статистики игроков", "Бан пользователей"
            ],
            AdminRank.ADMIN: [
                "Накрутка побед", "Очистка игр", "Просмотр статистики"
            ],
            AdminRank.HELPER: [
                "Просмотр статистики", "Очистка игр"
            ]
        }
        return permissions.get(rank, [])
    
    async def check_expired_games(self, context):
        """Проверяем и удаляем просроченные игры"""
        expired_games = []
        
        for game_id, game in list(self.games.items()):
            if game.is_expired(30):
                expired_games.append(game)
                del self.games[game_id]
        
        for game in expired_games:
            players = [game.player1, game.player2]
            for player_id in players:
                if player_id:
                    try:
                        await context.bot.send_message(
                            player_id, 
                            "⏰ Время вышло! Противник не сделал ход за 30 секунд.\nВозвращаем в главное меню...",
                            reply_markup=self.main_keyboard()
                        )
                    except:
                        pass
    
    async def start(self, update, context):
        user = update.effective_user
        
        # Проверяем бан
        if self.is_banned(user.id):
            ban_info = self.banned_users[user.id]
            await update.message.reply_text(
                f"🚫 Вы забанены!\n\n"
                f"📝 Причина: {ban_info['reason']}\n"
                f"⏰ Время бана: {ban_info['banned_at'].strftime('%Y-%m-%d %H:%M')}\n"
                f"👮 Админ: {ban_info['banned_by']}\n\n"
                f"Для разбана обратитесь к администрации."
            )
            return
        
        text = "🎮 Камень-Ножницы-Бумага\n\n/play - Играть\n/stats - Статистика\n/help - Помощь"
        
        if self.is_admin(user.id):
            text += "\n\n⚙️ Админ: /admin"
            
        await update.message.reply_text(text, reply_markup=self.main_keyboard())
    
    async def help_command(self, update, context):
        help_text = (
            "📖 Правила:\n"
            "• 🪨 Камень бьет ✂️ Ножницы\n"
            "• ✂️ Ножницы бьют 📄 Бумагу\n"
            "• 📄 Бумага бьет 🪨 Камень\n\n"
            "💡 Если противник не делает ход 30 секунд - игра автоматически отменяется!\n\n"
            "🔥 Винстрик (Win Streak):\n"
            "• Увеличивается с каждой победой подряд\n"
            "• Сбрасывается при поражении\n"
            "• Не сбрасывается при ничьей\n"
            "• Отображается в статистике /stats"
        )
        await update.message.reply_text(help_text)
    
    async def play(self, update, context):
        user_id = update.effective_user.id
        
        # Проверяем бан
        if self.is_banned(user_id):
            ban_info = self.banned_users[user_id]
            await update.message.reply_text(
                f"🚫 Вы забанены и не можете играть!\n\n"
                f"📝 Причина: {ban_info['reason']}\n"
                f"Для разбана обратитесь к администрации."
            )
            return
        
        await self.check_expired_games(context)
        
        for game in self.games.values():
            if user_id in [game.player1, game.player2] and not game.is_ready():
                await update.message.reply_text("⚠️ Вы уже в игре!")
                return
        
        for game in self.games.values():
            if game.player2 is None and user_id != game.player1:
                game.add_player(user_id)
                await update.message.reply_text("🎯 Противник найден! Выбирайте:", reply_markup=self.choice_keyboard())
                await context.bot.send_message(game.player1, "🎯 Противник найден! Выбирайте:", reply_markup=self.choice_keyboard())
                return
        
        self.game_counter += 1
        new_game = Game(self.game_counter, user_id)
        self.games[self.game_counter] = new_game
        await update.message.reply_text(f"🔍 Ищем противника... Игра #{self.game_counter}\n/cancel - Отмена")
    
    async def cancel(self, update, context):
        user_id = update.effective_user.id
        
        await self.check_expired_games(context)
        
        for game_id, game in list(self.games.items()):
            if user_id in [game.player1, game.player2]:
                opponent = game.player1 if user_id == game.player2 else game.player2
                del self.games[game_id]
                await update.message.reply_text("❌ Игра отменена", reply_markup=self.main_keyboard())
                if opponent:
                    await context.bot.send_message(opponent, "❌ Противник отменил игру", reply_markup=self.main_keyboard())
                return
        
        await update.message.reply_text("❌ Нет активных игр")
    
    async def handle_choice(self, update, context):
        user_id = update.effective_user.id
        
        await self.check_expired_games(context)
        
        game = None
        for g in self.games.values():
            if user_id in [g.player1, g.player2] and not g.is_ready():
                game = g
                break
        
        if not game:
            await update.callback_query.edit_message_text("❌ Игра не найдена")
            return
        
        choice_map = {"rock": Choice.ROCK, "scissors": Choice.SCISSORS, "paper": Choice.PAPER}
        game.make_choice(user_id, choice_map[update.callback_query.data])
        
        await update.callback_query.edit_message_text(f"✅ Выбрано: {choice_map[update.callback_query.data].value}\n⏳ Ждем противника...")
        
        if game.is_ready():
            await self.finish_game(game, context)
    
    async def finish_game(self, game, context):
        winner = game.get_winner()
        
        if winner:
            if winner == game.player1:
                self.update_stats(game.player1, "win")
                self.update_stats(game.player2, "loss")
                winner_text = "Игрок 1 🏆"
                
                # Проверяем винстрик победителя
                winner_streak = self.user_stats[game.player1]["win_streak"]
                if winner_streak >= 3:
                    winner_text += f" 🔥 {winner_streak} побед подряд!"
            else:
                self.update_stats(game.player1, "loss")
                self.update_stats(game.player2, "win")
                winner_text = "Игрок 2 🏆"
                
                # Проверяем винстрик победителя
                winner_streak = self.user_stats[game.player2]["win_streak"]
                if winner_streak >= 3:
                    winner_text += f" 🔥 {winner_streak} побед подряд!"
        else:
            self.update_stats(game.player1, "draw")
            self.update_stats(game.player2, "draw")
            winner_text = "🤝 Ничья"
        
        result = f"🎲 Игра #{game.id} завершена!\n\n{game.choice1.value} vs {game.choice2.value}\n\n{winner_text}"
        
        for player_id in [game.player1, game.player2]:
            if player_id:
                try:
                    await context.bot.send_message(player_id, result, reply_markup=self.main_keyboard())
                except:
                    pass
        
        del self.games[game.id]
    
    async def stats_command(self, update, context):
        user_id = update.effective_user.id
        
        await self.check_expired_games(context)
        
        if user_id not in self.user_stats:
            stats = {"wins": 0, "losses": 0, "draws": 0, "win_streak": 0, "max_win_streak": 0}
        else:
            stats = self.user_stats[user_id]
        
        total_games = stats["wins"] + stats["losses"] + stats["draws"]
        win_rate = (stats["wins"] / total_games * 100) if total_games > 0 else 0
        
        # Эмодзи для винстрика
        streak_emoji = "🔥" if stats["win_streak"] >= 5 else "⚡" if stats["win_streak"] >= 3 else "🎯"
        max_streak_emoji = "🏆" if stats["max_win_streak"] >= 10 else "⭐" if stats["max_win_streak"] >= 5 else "📈"
        
        stats_text = (
            f"📊 Ваша статистика:\n\n"
            f"🏆 Побед: {stats['wins']}\n"
            f"💔 Поражений: {stats['losses']}\n"
            f"🤝 Ничьих: {stats['draws']}\n"
            f"{streak_emoji} Текущий винстрик: {stats['win_streak']}\n"
            f"{max_streak_emoji} Макс. винстрик: {stats['max_win_streak']}\n"
            f"🎯 Всего игр: {total_games}\n"
            f"📈 Win Rate: {win_rate:.1f}%"
        )
        
        await update.message.reply_text(stats_text)
    
    async def admin(self, update, context):
        user_id = update.effective_user.id
        
        if not self.is_admin(user_id):
            await update.message.reply_text("❌ Доступ запрещен")
            return
        
        await self.check_expired_games(context)
        
        active_games = len([g for g in self.games.values() if not g.is_ready()])
        waiting_games = len([g for g in self.games.values() if g.player2 is None])
        total_users = len(self.user_stats)
        
        total_wins = sum(stats["wins"] for stats in self.user_stats.values())
        total_losses = sum(stats["losses"] for stats in self.user_stats.values())
        total_draws = sum(stats["draws"] for stats in self.user_stats.values())
        
        user_rank = self.get_admin_rank(user_id)
        
        admin_text = (
            f"⚙️ Админ-панель | {self.get_rank_name(user_rank)}\n\n"
            f"📈 Общая статистика:\n"
            f"• Активных игр: {active_games}\n"
            f"• Ожидают игроков: {waiting_games}\n"
            f"• Всего игр создано: {self.game_counter}\n"
            f"• Уникальных игроков: {total_users}\n"
            f"• Забанено: {len(self.banned_users)}\n\n"
            f"🎮 Статистика игр:\n"
            f"• Всего побед: {total_wins}\n"
            f"• Всего поражений: {total_losses}\n"
            f"• Всего ничьих: {total_draws}\n"
            f"• Всего сыграно: {total_wins + total_losses + total_draws}\n\n"
            f"👥 Админы: {len(self.admins)}\n\n"
            f"🛠️ Команды админа:\n"
        )
        
        # Показываем только доступные команды
        if self.has_permission(user_id, AdminRank.HELPER):
            admin_text += "/admin_cleanup - Очистка игр\n"
            admin_text += "/admin_stats - Топ игроков\n"
        
        if self.has_permission(user_id, AdminRank.ADMIN):
            admin_text += "/admin_boost - Накрутка побед\n"
        
        if self.has_permission(user_id, AdminRank.SUPER_ADMIN):
            admin_text += "/add_admin - Добавить админа\n"
            admin_text += "/remove_admin - Удалить админа\n"
            admin_text += "/reset_player_stats - Удалить статистику игрока\n"
            admin_text += "/ban - Забанить пользователя\n"
            admin_text += "/unban - Разбанить пользователя\n"
            admin_text += "/ban_list - Список банов\n"
        
        if self.has_permission(user_id, AdminRank.OWNER):
            admin_text += "/reset_all_stats - УДАЛИТЬ ВСЮ СТАТИСТИКУ\n"
        
        admin_text += "/list_admins - Список админов\n"
        admin_text += "/my_rank - Мой ранг"
        
        await update.message.reply_text(admin_text)
    
    async def admin_cleanup(self, update, context):
        if not self.has_permission(update.effective_user.id, AdminRank.HELPER):
            await update.message.reply_text("❌ Недостаточно прав")
            return
        
        initial_count = len(self.games)
        expired_games = []
        
        for game_id, game in list(self.games.items()):
            if game.is_expired(10):
                expired_games.append(game)
                del self.games[game_id]
        
        cleaned_count = initial_count - len(self.games)
        await update.message.reply_text(f"🧹 Очищено игр: {cleaned_count}\nОсталось: {len(self.games)}")
    
    async def admin_stats(self, update, context):
        if not self.has_permission(update.effective_user.id, AdminRank.HELPER):
            await update.message.reply_text("❌ Недостаточно прав")
            return
        
        top_players = sorted(
            [(user_id, stats) for user_id, stats in self.user_stats.items()],
            key=lambda x: x[1]["wins"],
            reverse=True
        )[:10]
        
        stats_text = "🏆 Топ игроков:\n\n"
        for i, (user_id, stats) in enumerate(top_players, 1):
            total_games = stats["wins"] + stats["losses"] + stats["draws"]
            win_rate = (stats["wins"] / total_games * 100) if total_games > 0 else 0
            streak_emoji = "🔥" if stats["win_streak"] >= 5 else "⚡" if stats["win_streak"] >= 3 else ""
            stats_text += f"{i}. ID {user_id}: {stats['wins']} побед ({win_rate:.1f}%) {streak_emoji}\n"
        
        await update.message.reply_text(stats_text)
    
    async def admin_boost(self, update, context):
        """Накрутка побед для админа"""
        if not self.has_permission(update.effective_user.id, AdminRank.ADMIN):
            await update.message.reply_text("❌ Недостаточно прав. Нужен ранг Админ или выше.")
            return
        
        if not context.args:
            await update.message.reply_text(
                "🎯 Накрутка побед\n\n"
                "Использование:\n"
                "/admin_boost [количество] - накрутить себе побед\n"
                "/admin_boost [ID] [количество] - накрутить другому игроку\n\n"
                "Пример:\n"
                "/admin_boost 10 - +10 побед себе\n"
                "/admin_boost 123456789 5 - +5 побед игроку 123456789"
            )
            return
        
        try:
            if len(context.args) == 1:
                user_id = update.effective_user.id
                wins_to_add = int(context.args[0])
                target = "себе"
            else:
                user_id = int(context.args[0])
                wins_to_add = int(context.args[1])
                target = f"игроку {user_id}"
            
            if wins_to_add <= 0:
                await update.message.reply_text("❌ Количество должно быть больше 0")
                return
            
            if wins_to_add > 1000:
                await update.message.reply_text("❌ Слишком много! Максимум 1000 за раз")
                return
            
            if user_id not in self.user_stats:
                self.user_stats[user_id] = {"wins": 0, "losses": 0, "draws": 0, "win_streak": 0, "max_win_streak": 0}
            
            # Добавляем победы и обновляем винстрик
            self.user_stats[user_id]["wins"] += wins_to_add
            self.user_stats[user_id]["win_streak"] += wins_to_add
            if self.user_stats[user_id]["win_streak"] > self.user_stats[user_id]["max_win_streak"]:
                self.user_stats[user_id]["max_win_streak"] = self.user_stats[user_id]["win_streak"]
            
            stats = self.user_stats[user_id]
            total_games = stats["wins"] + stats["losses"] + stats["draws"]
            win_rate = (stats["wins"] / total_games * 100) if total_games > 0 else 0
            
            await update.message.reply_text(
                f"✅ Успешно добавлено {wins_to_add} побед {target}!\n\n"
                f"📊 Новая статистика:\n"
                f"🏆 Побед: {stats['wins']}\n"
                f"💔 Поражений: {stats['losses']}\n"
                f"🤝 Ничьих: {stats['draws']}\n"
                f"🔥 Винстрик: {stats['win_streak']}\n"
                f"⭐ Макс. винстрик: {stats['max_win_streak']}\n"
                f"📈 Win Rate: {win_rate:.1f}%"
            )
            
        except ValueError:
            await update.message.reply_text("❌ Неверный формат. Используйте числа.")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    def choice_keyboard(self):
        buttons = [
            [InlineKeyboardButton("🪨 Камень", callback_data="rock"),
             InlineKeyboardButton("✂️ Ножницы", callback_data="scissors"),
             InlineKeyboardButton("📄 Бумага", callback_data="paper")]
        ]
        return InlineKeyboardMarkup(buttons)
    
    def main_keyboard(self):
        return ReplyKeyboardMarkup([["/play", "/stats", "/help"]], resize_keyboard=True)
    
    def setup(self, app):
        app.add_handler(CommandHandler("start", self.start))
        app.add_handler(CommandHandler("play", self.play))
        app.add_handler(CommandHandler("cancel", self.cancel))
        app.add_handler(CommandHandler("stats", self.stats_command))
        app.add_handler(CommandHandler("help", self.help_command))
        app.add_handler(CommandHandler("admin", self.admin))
        app.add_handler(CommandHandler("admin_cleanup", self.admin_cleanup))
        app.add_handler(CommandHandler("admin_stats", self.admin_stats))
        app.add_handler(CommandHandler("admin_boost", self.admin_boost, has_args=True))
        app.add_handler(CommandHandler("add_admin", self.add_admin, has_args=True))
        app.add_handler(CommandHandler("remove_admin", self.remove_admin, has_args=True))
        app.add_handler(CommandHandler("list_admins", self.list_admins))
        app.add_handler(CommandHandler("my_rank", self.my_rank))
        app.add_handler(CommandHandler("reset_all_stats", self.reset_all_stats, has_args=True))
        app.add_handler(CommandHandler("reset_player_stats", self.reset_player_stats, has_args=True))
        app.add_handler(CommandHandler("ban", self.ban_user, has_args=True))
        app.add_handler(CommandHandler("unban", self.unban_user, has_args=True))
        app.add_handler(CommandHandler("ban_list", self.ban_list))
        app.add_handler(CallbackQueryHandler(self.handle_choice))

def main():
    BOT_TOKEN = "8357338183:AAHGtYrjCMNlk4GSmKcW4z_8uUbu4MaY_wY"
    
    app = Application.builder().token(BOT_TOKEN).build()
    bot = GameBot()
    bot.setup(app)
    
    print("🤖 Бот запущен!")
    print("🎖️ Система рангов админов активирована")
    print("👑 Владелец: 7296765144")
    print("🔥 Винстрик система добавлена")
    print("🔨 Система банов активирована")
    print("✅ Таймер 30 секунд включен")
    app.run_polling()

if __name__ == "__main__":
    main()
