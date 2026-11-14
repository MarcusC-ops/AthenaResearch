from django.urls import path

from . import views

app_name = 'storefront'

urlpatterns = [
    path('', views.home, name='home'),
    path('studies/', views.studies, name='studies'),
    path('studies/<slug:slug>/', views.study_detail, name='study_detail'),
    path('support/', views.support, name='support'),
    path('onboarding/', views.onboarding, name='onboarding'),
    path('for-you/', views.for_you, name='for_you'),
    path('shortlist/', views.shortlist, name='shortlist'),
    path('shortlist/add/<int:study_id>/', views.shortlist_add, name='shortlist_add'),
    path('shortlist/remove/<int:study_id>/', views.shortlist_remove, name='shortlist_remove'),
    path('shortlist/compare/', views.shortlist_compare, name='shortlist_compare'),
]
