from django.urls import path
from . import views

app_name = 'cards'

urlpatterns = [
    # Главная страница
    path('', views.home, name='home'),

    # Регистрация (остаётся в cards, т.к. кастомная)
    path('register/', views.register, name='register'),

    # Список карточек
    path('cards/', views.card_list, name='card_list'),

    # Добавление, удаление и редактирование карточки
    path('add/', views.add_card, name='add_card'),
    path('edit/<int:card_id>/', views.edit_card, name='edit_card'),
    path('delete/<int:card_id>/', views.delete_card, name='delete_card'),

    # Режим повторения
    path('review/', views.review, name='review'),
    path('review/<int:card_id>/answer/<str:difficulty>/', views.review_answer, name='review_answer'),

    # Экспорт и импорт
    path('export/', views.export_cards, name='export_cards'),
    path('import/', views.import_cards, name='import_cards'),

    # Озвучка
    path('say/<str:word>/', views.say_word, name='say_word'),
]