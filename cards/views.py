from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.http import HttpResponse
from django.utils import timezone
from django.contrib.auth.models import User
from .models import Card, Schedule, UserStats
import json

# ===========================
# Главная и регистрация
# ===========================

def home(request):
    if request.user.is_authenticated:
        return redirect('cards:card_list')
    return render(request, 'home.html')


def register(request):
    """
    Регистрация нового пользователя
    """
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            # Создаём UserStats для нового пользователя
            UserStats.objects.get_or_create(user=user)
            return redirect('cards:card_list')
    else:
        form = UserCreationForm()
    return render(request, 'register.html', {"form": form})


# ===========================
# Работа с карточками
# ===========================

@login_required
def card_list(request):
    """
    Список всех карточек с фильтрацией по уровню
    """
    level = request.GET.get('level')
    cards = Card.objects.filter(owner=request.user)
    if level in ['beginner', 'intermediate', 'advanced']:
        cards = cards.filter(level=level)
    
    due_cards = Card.objects.filter(
        owner=request.user,
        schedule__next_review__lte=timezone.now()
    )

    # Подсчёт статистики
    total_cards = cards.count()
    beginner_count = cards.filter(level='beginner').count()
    intermediate_count = cards.filter(level='intermediate').count()
    advanced_count = cards.filter(level='advanced').count()
    due_count = due_cards.count()

    return render(request, 'cards/card_list.html', {
        'cards': cards,
        'due_cards': due_cards,
        'total_cards': total_cards,
        'beginner_count': beginner_count,
        'intermediate_count': intermediate_count,
        'advanced_count': advanced_count,
        'due_count': due_count
    })


@login_required
def add_card(request):
    """
    Добавление новой карточки
    """
    if request.method == "POST":
        word = request.POST.get('word')
        translation = request.POST.get('translation')
        example = request.POST.get('example', '')
        note = request.POST.get('note', '')
        level = request.POST.get('level', 'beginner')

        if word and translation:
            card = Card.objects.create(
                owner=request.user,
                word=word,
                translation=translation,
                example=example,
                note=note,
                level=level
            )
            # Создаём расписание
            Schedule.objects.create(card=card)
            return redirect('cards:card_list')
    return render(request, 'cards/card_form.html')


@login_required
def edit_card(request, card_id):
    """
    Редактирование карточки
    """
    card = get_object_or_404(Card, id=card_id, owner=request.user)
    if request.method == "POST":
        card.word = request.POST.get('word')
        card.translation = request.POST.get('translation')
        card.example = request.POST.get('example', '')
        card.note = request.POST.get('note', '')
        card.level = request.POST.get('level', 'beginner')
        card.save()
        return redirect('cards:card_list')
    return render(request, 'cards/card_form.html', {'card': card})


# ===========================
# Режим повторения
# ===========================

@login_required
def review(request):
    """
    Повторение слов на сегодня
    """
    due_cards = Card.objects.filter(
        owner=request.user,
        schedule__next_review__lte=timezone.now()
    ).order_by('schedule__next_review')

    if not due_cards:
        return render(request, 'cards/review_done.html')

    card = due_cards.first()
    return render(request, 'cards/review.html', {'card': card})


@login_required
def review_answer(request, card_id, difficulty):
    """
    Обработка ответа на повторение
    """
    card = get_object_or_404(Card, id=card_id, owner=request.user)
    schedule = card.schedule

    # Обновляем расписание
    schedule.update_schedule(difficulty)

    # Обновляем статистику пользователя
    user_stats = request.user.userstats
    user_stats.last_reviewed = timezone.now()
    user_stats.review_streak += 1
    user_stats.save()

    return redirect('cards:review')


# ===========================
# Экспорт / Импорт
# ===========================

@login_required
def export_cards(request):
    """
    Экспорт карточек в JSON
    """
    cards = Card.objects.filter(owner=request.user).values(
        'word', 'translation', 'example', 'note', 'level'
    )
    data = list(cards)
    response = HttpResponse(
        json.dumps(data, ensure_ascii=False, indent=2),
        content_type='application/json'
    )
    response['Content-Disposition'] = 'attachment; filename="my_cards.json"'
    return response


@login_required
def import_cards(request):
    """
    Импорт карточек из JSON
    """
    if request.method == 'POST' and request.FILES.get('file'):
        file = request.FILES['file']
        try:
            data = json.loads(file.read().decode('utf-8'))
            imported = 0
            for item in data:
                Card.objects.get_or_create(
                    owner=request.user,
                    word=item['word'],
                    defaults={
                        'translation': item['translation'],
                        'example': item.get('example', ''),
                        'note': item.get('note', ''),
                        'level': item.get('level', 'beginner')
                    }
                )
                imported += 1
            return render(request, 'cards/import_success.html', {'imported': imported})
        except Exception as e:
            return render(request, 'cards/import_error.html', {'error': str(e)})

    return render(request, 'cards/import_form.html')