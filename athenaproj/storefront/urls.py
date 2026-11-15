from django.urls import path

from . import views

app_name = 'storefront'

urlpatterns = [
    path('', views.home, name='home'),
    path('studies/', views.studies, name='studies'),
    path('studies/<slug:slug>/', views.study_detail, name='study_detail'),
    path('studies/<slug:slug>/apply/step-1/', views.apply_step1, name='apply_step1'),
    path('studies/<slug:slug>/apply/step-2/', views.apply_step2, name='apply_step2'),
    path('studies/<slug:slug>/apply/step-3/', views.apply_step3, name='apply_step3'),
    path('applications/<int:application_id>/', views.application_detail, name='application_detail'),
    path('applications/<int:application_id>/submitted/', views.application_submitted, name='application_submitted'),
    path('support/', views.support, name='support'),
    path('onboarding/', views.onboarding, name='onboarding'),
    path('for-you/', views.for_you, name='for_you'),
    path('shortlist/', views.shortlist, name='shortlist'),
    path('shortlist/add/<int:study_id>/', views.shortlist_add, name='shortlist_add'),
    path('shortlist/remove/<int:study_id>/', views.shortlist_remove, name='shortlist_remove'),
    path('shortlist/compare/', views.shortlist_compare, name='shortlist_compare'),
]
