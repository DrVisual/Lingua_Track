from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views

urlpatterns = [
    # Админка
    path('admin/', admin.site.urls),

    # Подключаем все маршруты из приложения 'cards'
    path('', include('cards.urls')),

    # Вход (использует шаблон login.html)
    path('login/', auth_views.LoginView.as_view(
        template_name='login.html',
        success_url='/'  # После входа — на главную
    ), name='login'),

    # Выход (после выхода — на главную)
    path('logout/', auth_views.LogoutView.as_view(
        next_page='/'
    ), name='logout'),
]