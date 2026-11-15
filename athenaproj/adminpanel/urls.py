from django.urls import path

from . import views

app_name = 'adminpanel'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('login/', views.panel_login, name='login'),
    path('logout/', views.PanelLogoutView.as_view(), name='logout'),
    path('notifications/', views.notifications, name='notifications'),
    path('notifications/read/', views.mark_notifications_read, name='mark_notifications_read'),
    path('studies/', views.study_list, name='study_list'),
    path('studies/new/', views.study_new, name='study_new'),
    path('studies/<int:study_id>/', views.study_detail, name='study_detail'),
    path('studies/<int:study_id>/edit/', views.study_edit, name='study_edit'),
    path('studies/<int:study_id>/questions/', views.study_questions, name='study_questions'),
    path(
        'studies/<int:study_id>/questions/<int:question_id>/edit/',
        views.study_question_edit,
        name='study_question_edit',
    ),
    path(
        'studies/<int:study_id>/questions/<int:question_id>/delete/',
        views.study_question_delete,
        name='study_question_delete',
    ),
    path('studies/<int:study_id>/preview/', views.study_preview, name='study_preview'),
    path('studies/<int:study_id>/submit/', views.study_submit, name='study_submit'),
    path(
        'studies/<int:study_id>/applicants/',
        views.applicants,
        name='applicants',
    ),
    path(
        'applications/<int:application_id>/',
        views.application_detail,
        name='application_detail',
    ),
    path(
        'applications/<int:application_id>/not-selected/',
        views.application_not_selected,
        name='application_not_selected',
    ),
    path(
        'applications/<int:application_id>/screening-failed/',
        views.application_screening_failed,
        name='application_screening_failed',
    ),
    path(
        'applications/<int:application_id>/override/',
        views.application_override,
        name='application_override',
    ),
    path(
        'applications/<int:application_id>/override/confirm/',
        views.application_override_confirm,
        name='application_override_confirm',
    ),
    path('participation/', views.participation, name='participation'),
    path('participation/<int:application_id>/', views.participation_detail, name='participation_detail'),
    path('participation/<int:application_id>/withdraw/', views.participation_withdraw, name='participation_withdraw'),
    path('insights/', views.insights, name='insights'),
]
