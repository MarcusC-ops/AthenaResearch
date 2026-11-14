from django.urls import include, path
from accounts.views import profile

urlpatterns = [
    path('', include('storefront.urls')),
    path('accounts/', include('accounts.urls')),
    path('panel/', include('adminpanel.urls')),
    path('account/', profile, name='profile'),
]
