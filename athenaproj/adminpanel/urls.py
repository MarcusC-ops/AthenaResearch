from django.urls import path

from . import views

app_name = 'adminpanel'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('login/', views.panel_login, name='login'),
    path('logout/', views.PanelLogoutView.as_view(), name='logout'),
    path('notifications/', views.notifications, name='notifications'),
    path('notifications/read/', views.mark_notifications_read, name='mark_notifications_read'),
]
