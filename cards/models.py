# cards/models.py

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta

# Уровни сложности карточки
LEVEL_CHOICES = [
    ('beginner', 'Начальный'),
    ('intermediate', 'Средний'),
    ('advanced', 'Продвинутый'),
]


class Card(models.Model):
    word = models.CharField("Слово", max_length=200)
    translation = models.CharField("Перевод", max_length=200)
    example = models.TextField("Пример использования", blank=True, null=True)
    note = models.TextField("Примечание", blank=True, null=True)
    level = models.CharField("Уровень", max_length=20, choices=LEVEL_CHOICES, default='beginner')
    owner = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Владелец")
    created_at = models.DateTimeField("Дата создания", auto_now_add=True)

    def __str__(self):
        return f"{self.word} → {self.translation}"

    class Meta:
        verbose_name = "Карточка"
        verbose_name_plural = "Карточки"


class Schedule(models.Model):
    card = models.OneToOneField(Card, on_delete=models.CASCADE, verbose_name="Карточка")
    next_review = models.DateTimeField("Следующее повторение", default=timezone.now)
    ease_factor = models.FloatField("Фактор лёгкости", default=2.5)
    interval = models.IntegerField("Интервал (дни)", default=1)
    repetitions = models.IntegerField("Число повторений", default=0)

    def __str__(self):
        return f"{self.card.word} → {self.next_review}"

    class Meta:
        verbose_name = "Расписание"
        verbose_name_plural = "Расписание повторений"

    def update_schedule(self, difficulty):
        """
        Обновляет расписание по SM-2 и сохраняет в БД.
        """
        if difficulty == 'hard':
            self.interval = max(1, int(self.interval * 1.2))
        elif difficulty == 'good':
            self.interval = int(self.interval * 2.5)
        elif difficulty == 'easy':
            self.interval = int(self.interval * 3.5)
        else:
            self.interval = 1

        if difficulty == 'hard':
            self.ease_factor = max(1.3, self.ease_factor - 0.2)
        elif difficulty == 'good':
            self.ease_factor = max(1.3, self.ease_factor + 0.1)
        elif difficulty == 'easy':
            self.ease_factor = max(1.3, self.ease_factor + 0.3)

        self.repetitions += 1
        self.next_review = timezone.now() + timedelta(days=self.interval)

        # ✅ Сохраняем изменения
        self.save()


class UserStats(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, verbose_name="Пользователь")
    telegram_id = models.CharField("Telegram ID", max_length=50, blank=True, null=True)
    total_cards = models.IntegerField("Всего карточек", default=0)
    learned_cards = models.IntegerField("Выучено карточек", default=0)
    review_streak = models.IntegerField("Серия повторений", default=0)
    last_reviewed = models.DateTimeField("Последнее повторение", blank=True, null=True)
    reminder_time = models.TimeField("Время напоминания", default="09:00")

    def __str__(self):
        return f"Статистика {self.user.username}"

    class Meta:
        verbose_name = "Статистика пользователя"
        verbose_name_plural = "Статистика пользователей"