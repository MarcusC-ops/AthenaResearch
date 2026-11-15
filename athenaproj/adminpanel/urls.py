from django.urls import path

from . import views

app_name = 'adminpanel'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('moderation/', views.moderation, name='moderation'),
    path('moderation/<int:study_id>/', views.moderation_detail, name='moderation_detail'),
    path(
        'moderation/<int:study_id>/unpublish/',
        views.moderation_unpublish,
        name='moderation_unpublish',
    ),
    path('organisations/', views.organisations, name='organisations'),
    path(
        'organisations/<int:organisation_id>/',
        views.organisation_detail,
        name='organisation_detail',
    ),
    path(
        'organisations/<int:organisation_id>/sites/',
        views.organisation_sites,
        name='organisation_sites',
    ),
    path(
        'organisations/<int:organisation_id>/sites/<int:site_id>/edit/',
        views.site_edit,
        name='site_edit',
    ),
    path(
        'organisations/<int:organisation_id>/sites/<int:site_id>/delete/',
        views.site_delete_confirmation,
        name='site_delete',
    ),
    path(
        'organisations/<int:organisation_id>/users/',
        views.organisation_users,
        name='organisation_users',
    ),
    path(
        'organisations/<int:organisation_id>/<str:action>/',
        views.organisation_active_confirmation,
        name='organisation_active',
    ),
    path(
        'organisations/<int:organisation_id>/sites/<int:site_id>/<str:action>/',
        views.site_active_confirmation,
        name='site_active',
    ),
    path('participants/', views.participants, name='participants'),
    path(
        'participants/<int:participant_id>/',
        views.participant_detail,
        name='participant_detail',
    ),
    path('taxonomy/', views.taxonomy, name='taxonomy'),
    path(
        'taxonomy/categories/new/',
        views.taxonomy_category_save,
        name='taxonomy_category_new',
    ),
    path(
        'taxonomy/categories/<int:category_id>/edit/',
        views.taxonomy_category_save,
        name='taxonomy_category_edit',
    ),
    path(
        'taxonomy/conditions/new/',
        views.taxonomy_condition_save,
        name='taxonomy_condition_new',
    ),
    path(
        'taxonomy/conditions/<int:condition_id>/edit/',
        views.taxonomy_condition_save,
        name='taxonomy_condition_edit',
    ),
    path(
        'taxonomy/<str:kind>/<int:record_id>/delete/',
        views.taxonomy_delete,
        name='taxonomy_delete',
    ),
    path(
        'taxonomy/<str:kind>/<int:record_id>/<str:action>/',
        views.taxonomy_active,
        name='taxonomy_active',
    ),
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
    path('payouts/', views.payouts, name='payouts'),
    path('payouts/pay/', views.payout_pay, name='payout_pay'),
    path('payouts/<int:payout_id>/reject/', views.payout_reject, name='payout_reject'),
    path('reviews/', views.reviews, name='reviews'),
    path('reviews/<int:review_id>/reject/', views.review_reject, name='review_reject'),
    path('support/', views.support, name='support'),
    path('support/<int:support_id>/', views.support_detail, name='support_detail'),
    path('ml/', views.ml_monitor, name='ml_monitor'),
    path('ml/settings/', views.ml_settings, name='ml_settings'),
    path('staff/', views.staff_accounts, name='staff_accounts'),
    path(
        'staff/<int:user_id>/<str:action>/',
        views.staff_account_action,
        name='staff_account_action',
    ),
    path('demo-data/', views.demo_data, name='demo_data'),
]
