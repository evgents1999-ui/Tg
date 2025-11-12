import os
import logging
import asyncio
from enum import Enum
from datetime import datetime
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class Choice(Enum):
    ROCK = "🪨 Камень"
    SCISSORS = "✂️ Ножницы"
    PAPER = "📄 Бумага"

class AdminRank(Enum):
    OWNER = 4
    SUPER_ADMIN = 3
    ADMIN = 2
    HELPER = 1

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
        self.admins = {
            7296765144: AdminRank.OWNER,
        }
        self.user_stats = {}
        self.banned_users = {}
    
    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admins
    
    def is_banned(self, user_id: int) -> bool:
        return user_id in self.banned_users
    
    def get_admin_rank(self, user_id: int) -> AdminRank:
        return self.admins.get(user_id)
    
    def has_permission(self, user_id: int, required_rank: AdminRank) -> bool:
        if not self.is_admin(user_id):
            return False
        return self.admins[user_id].value >= required_rank.value
    
    def get_rank_name(self, rank: AdminRank) -> str:
        names = {
            AdminRank.OWNER: "👑 Владелец",
            AdminRank.SUPER_ADMIN: "⚡ Супер-Админ", 
            AdminRank.ADMIN: "🔧 Админ",
            AdminRank.HELPER: "🛠️ Помощник"
        }
        return names.get(rank, "❓ Неизвестно")
    
    async def ban_user(self, update, context):
        user_id = update.effective_user.id
        
        if not self.has_permission(user_id, AdminRank.SUPER_ADMIN):
            await update.message.reply_text("❌ Недостаточно прав.")
            return
        
        if not context.args or len(context.args) < 2:
            await update.message.reply_text("Использование: /ban [ID] [причина]")
            return
        
        try:
            target_id = int(context.args[0])
            reason = " ".join(context.args[1:])
            
            if target_id in self.admins:
                await update.message.reply_text("❌ Нельзя забанить админа")
                return
            
            if self.is_banned(target_id):
                await update.message.reply_text("❌ Уже забанен")
                return
            
            self.banned_users[target_id] = {
                "reason": reason,
                "banned_by": user_id,
                "banned_at": datetime.now()
            }
            
            for game_id, game in list(self.games.items()):
                if target_id in [game.player1, game.player2]:
                    opponent = game.player1 if target_id == game.player2 else game.player2
                    del self.games[game_id]
                    if opponent:
                        try:
                            await context.bot.send_message(opponent, "❌ Игра отменена - противник забанен")
                        except:
                            pass
            
            await update.message.reply_text(f"🔨 Пользователь {target_id} забанен!")
            
        except ValueError:
            await update.message.reply_text("❌ Неверный ID")
    
    async def unban_user(self, update, context):
        user_id = update.effective_user.id
        
        if not self.has_permission(user_id, AdminRank.SUPER_ADMIN):
            await update.message.reply_text("❌ Недостаточно прав.")
            return
        
        if not context.args:
            await update.message.reply_text("Использование: /unban [ID]")
            return
        
        try:
            target_id = int(context.args[0])
            
            if not self.is_banned(target_id):
                await update.message.reply_text("❌ Не забанен")
                return
            
            self.banned_users.pop(target_id)
            await update.message.reply_text(f"🔓 Пользователь {target_id} разбанен!")
            
        except ValueError:
            await update.message.reply_text("❌ Неверный ID")
    
    async def ban_list(self, update, context):
        user_id = update.effective_user.id
        
        if not self.has_permission(user_id, AdminRank.SUPER_ADMIN):
            await update.message.reply_text("❌ Недостаточно прав.")
            return
        
        if not self.banned_users:
            await update.message.reply_text("📋 Список банов пуст")
            return
        
        ban_list = "🔨 Забаненные:\n\n"
        for banned_id, ban_info in self.banned_users.items():
            ban_list += f"👤 {banned_id}\n📝 {ban_info['reason']}\n\n"
        
        await update.message.reply_text(ban_list)
    
    def update_stats(self, user_id, result):
        if user_id not in self.user_stats:
            self.user_stats[user_id] = {
                "wins": 0, "losses": 0, "draws": 0, 
                "win_streak": 0, "max_win_streak": 0
            }
        
        stats = self.user_stats[user_id]
        
        if result == "win":
            stats["wins"] += 1
            stats["win_streak"] += 1
            if stats["win_streak"] > stats["max_win_streak"]:
                stats["max_win_streak"] = stats["win_streak"]
        elif result == "loss":
            stats["losses"] += 1
            stats["win_streak"] = 0
        elif result == "draw":
            stats["draws"] += 1
    
    async def start(self, update, context):
        user = update.effective_user
        
        if self.is_banned(user.id):
            ban_info = self.banned_users[user.id]
            await update.message.reply_text(f"🚫 Вы забанены! Причина: {ban_info['reason']}")
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
            "💡 Таймаут: 30 секунд\n"
            "🔥 Винстрик увеличивается с победами!"
        )
        await update.message.reply_text(help_text)
    
    async def play(self, update, context):
        user_id = update.effective_user.id
        
        if self.is_banned(user_id):
            await update.message.reply_text("🚫 Вы забанены!")
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
        choice = update.callback_query.data
        await update.callback_query.answer()
        
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
        game.make_choice(user_id, choice_map[choice])
        
        await update.callback_query.edit_message_text(f"✅ Выбрано: {choice_map[choice].value}\n⏳ Ждем противника...")
        
        if game.is_ready():
            await self.finish_game(game, context)
    
    async def finish_game(self, game, context):
        winner = game.get_winner()
        
        if winner:
            if winner == game.player1:
                self.update_stats(game.player1, "win")
                self.update_stats(game.player2, "loss")
                winner_text = "Игрок 1 🏆"
                winner_streak = self.user_stats[game.player1]["win_streak"]
                if winner_streak >= 3:
                    winner_text += f" 🔥 {winner_streak} побед подряд!"
            else:
                self.update_stats(game.player1, "loss")
                self.update_stats(game.player2, "win")
                winner_text = "Игрок 2 🏆"
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
        
        streak_emoji = "🔥" if stats["win_streak"] >= 5 else "⚡" if stats["win_streak"] >= 3 else "🎯"
        
        stats_text = (
            f"📊 Ваша статистика:\n\n"
            f"🏆 Побед: {stats['wins']}\n"
            f"💔 Поражений: {stats['losses']}\n"
            f"🤝 Ничьих: {stats['draws']}\n"
            f"{streak_emoji} Винстрик: {stats['win_streak']}\n"
            f"⭐ Макс. винстрик: {stats['max_win_streak']}\n"
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
        user_rank = self.get_admin_rank(user_id)
        
        admin_text = (
            f"⚙️ Админ-панель | {self.get_rank_name(user_rank)}\n\n"
            f"📈 Статистика:\n"
            f"• Активных игр: {active_games}\n"
            f"• Всего игр: {self.game_counter}\n"
            f"• Игроков: {len(self.user_stats)}\n"
            f"• Забанено: {len(self.banned_users)}\n\n"
            f"🛠️ Команды:\n"
        )
        
        if self.has_permission(user_id, AdminRank.HELPER):
            admin_text += "/admin_stats - Топ игроков\n"
        
        if self.has_permission(user_id, AdminRank.ADMIN):
            admin_text += "/admin_boost - Накрутка побед\n"
        
        if self.has_permission(user_id, AdminRank.SUPER_ADMIN):
            admin_text += "/ban - Бан\n/unban - Разбан\n/ban_list - Список банов\n"
        
        admin_text += "/my_rank - Мой ранг"
        
        await update.message.reply_text(admin_text)
    
    async def admin_stats(self, update, context):
        if not self.has_permission(update.effective_user.id, AdminRank.HELPER):
            await update.message.reply_text("❌ Недостаточно прав")
            return
        
        top_players = sorted(
            [(user_id, stats) for user_id, stats in self.user_stats.items()],
            key=lambda x: x[1]["wins"],
            reverse=True
        )[:5]
        
        stats_text = "🏆 Топ игроков:\n\n"
        for i, (user_id, stats) in enumerate(top_players, 1):
            total_games = stats["wins"] + stats["losses"] + stats["draws"]
            win_rate = (stats["wins"] / total_games * 100) if total_games > 0 else 0
            stats_text += f"{i}. ID {user_id}: {stats['wins']} побед ({win_rate:.1f}%)\n"
        
        await update.message.reply_text(stats_text)
    
    async def admin_boost(self, update, context):
        if not self.has_permission(update.effective_user.id, AdminRank.ADMIN):
            await update.message.reply_text("❌ Недостаточно прав.")
            return
        
        if not context.args:
            await update.message.reply_text("Использование: /admin_boost [кол-во] или /admin_boost [ID] [кол-во]")
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
            
            if wins_to_add <= 0 or wins_to_add > 1000:
                await update.message.reply_text("❌ От 1 до 1000")
                return
            
            if user_id not in self.user_stats:
                self.user_stats[user_id] = {"wins": 0, "losses": 0, "draws": 0, "win_streak": 0, "max_win_streak": 0}
            
            self.user_stats[user_id]["wins"] += wins_to_add
            self.user_stats[user_id]["win_streak"] += wins_to_add
            if self.user_stats[user_id]["win_streak"] > self.user_stats[user_id]["max_win_streak"]:
                self.user_stats[user_id]["max_win_streak"] = self.user_stats[user_id]["win_streak"]
            
            stats = self.user_stats[user_id]
            
            await update.message.reply_text(
                f"✅ +{wins_to_add} побед {target}!\n"
                f"🏆 Побед: {stats['wins']}\n"
                f"🔥 Винстрик: {stats['win_streak']}"
            )
            
        except ValueError:
            await update.message.reply_text("❌ Неверный формат")
    
    async def check_expired_games(self, context):
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
                            "⏰ Время вышло! Игра отменена.",
                            reply_markup=self.main_keyboard()
                        )
                    except:
                        pass
    
    def choice_keyboard(self):
        buttons = [
            [InlineKeyboardButton("🪨 Камень", callback_data="rock"),
             InlineKeyboardButton("✂️ Ножницы", callback_data="scissors"),
             InlineKeyboardButton("📄 Бумага", callback_data="paper")]
        ]
        return InlineKeyboardMarkup(buttons)
    
    def main_keyboard(self):
        return ReplyKeyboardMarkup([["/play", "/stats", "/help"]], resize_keyboard=True)
    
    def setup_handlers(self, application):
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("play", self.play))
        application.add_handler(CommandHandler("cancel", self.cancel))
        application.add_handler(CommandHandler("stats", self.stats_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("admin", self.admin))
        application.add_handler(CommandHandler("admin_stats", self.admin_stats))
        application.add_handler(CommandHandler("admin_boost", self.admin_boost, has_args=True))
        application.add_handler(CommandHandler("ban", self.ban_user, has_args=True))
        application.add_handler(CommandHandler("unban", self.unban_user, has_args=True))
        application.add_handler(CommandHandler("ban_list", self.ban_list))
        application.add_handler(CallbackQueryHandler(self.handle_choice))

def main():
    # Получаем токен из переменных окружения
    BOT_TOKEN = os.getenv('BOT_TOKEN', '8357338183:AAHGtYrjCMNlk4GSmKcW4z_8uUbu4MaY_wY')
    
    if not BOT_TOKEN:
        print("❌ Ошибка: BOT_TOKEN не установлен")
        return
    
    application = Application.builder().token(BOT_TOKEN).build()
    bot = GameBot()
    bot.setup_handlers(application)
    
    print("🤖 Бот запущен на хостинге!")
    application.run_polling()

if __name__ == "__main__":
    main()
