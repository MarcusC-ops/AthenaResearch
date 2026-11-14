from django.urls import include, path

urlpatterns = [
    path('', include('storefront.urls')),
    path('accounts/', include('accounts.urls')),
    path('panel/', include('adminpanel.urls')),
]
